"""The chat backend, driven by a fake agent that speaks the same protocol.

The real thing is Claude Code with `--input-format stream-json`; the shapes
here were captured from it (2.1.273) rather than guessed. Using a scripted
child means the whole translation can be exercised without spending a
subscription turn on every run.
"""
import io
import json
import queue
import sys
import textwrap

import pytest

import chat

# A child that reads the same stdin protocol and answers on stdout. It covers
# the three things the page renders: streamed text, a tool call with its
# result, and the end of a turn.
FAKE_AGENT = textwrap.dedent("""
    import json, sys
    def out(obj):
        sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()
    def stream(inner):
        out({"type": "stream_event", "event": inner})
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") == "control_request":
            out({"type": "control_response", "response": {"subtype": "success"}})
            out({"type": "result", "subtype": "error_during_execution",
                 "is_error": True, "terminal_reason": "aborted_tools", "result": None})
            continue
        text = msg.get("message", {}).get("content")
        if text == "boom":
            out({"type": "result", "subtype": "error_during_execution",
                 "is_error": True, "result": "something went wrong"})
            continue
        out({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "echo hi", "description": "say hi"}}]}})
        out({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "hi",
             "is_error": False}]}})
        # A text block and a tool block inside one message, the way the real
        # agent interleaves them: block 0 holds the text and stays open while
        # block 1 opens and closes in the middle of it.
        stream({"type": "message_start"})
        stream({"type": "content_block_start", "index": 0,
                "content_block": {"type": "text", "text": ""}})
        stream({"type": "content_block_delta", "index": 0,
                "delta": {"type": "text_delta", "text": "It "}})
        stream({"type": "content_block_start", "index": 1,
                "content_block": {"type": "tool_use", "id": "t2",
                                  "name": "Bash", "input": {}}})
        stream({"type": "content_block_delta", "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": "{}"}})
        stream({"type": "content_block_stop", "index": 1})
        for piece in ("printed ", "hi."):
            stream({"type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": piece}})
        stream({"type": "content_block_stop", "index": 0})
        out({"type": "result", "subtype": "success", "is_error": False,
             "terminal_reason": "completed", "result": "It printed hi."})
""")


@pytest.fixture
def agent(tmp_path):
    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    made = chat.Agent(command=[sys.executable, "-u", str(script)], cwd=str(tmp_path))
    yield made
    made.reset()


def drain(channel, until, timeout=10):
    """Collect events until one of type `until`, or give up."""
    got = []
    while True:
        try:
            event = channel.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"never saw {until}; got {got}") from None
        got.append(event)
        if event.get("t") == until:
            return got


def test_a_turn_streams_text_and_reports_its_tool(agent):
    channel = agent.subscribe()
    assert agent.send("hello")[0] == 200
    events = drain(channel, "turn")

    kinds = [e["t"] for e in events]
    assert kinds.count("tool") == 1
    assert kinds.count("tool_done") == 1
    # Text arrives as deltas between a start and a stop, so the bubble can
    # fill in rather than appearing all at once.
    assert kinds.index("say_start") < kinds.index("say") < kinds.index("say_end")
    said = "".join(e["text"] for e in events if e["t"] == "say")
    assert said == "It printed hi."

    tool = next(e for e in events if e["t"] == "tool")
    assert tool["name"] == "Bash"
    assert tool["detail"] == "echo hi"
    assert next(e for e in events if e["t"] == "tool_done")["ok"] is True
    assert events[-1] == {"t": "turn", "status": "done", "text": ""}


def test_the_finished_assistant_text_is_not_rendered_twice(agent):
    """The same words arrive as deltas and again in the finished message."""
    channel = agent.subscribe()
    agent.send("hello")
    events = drain(channel, "turn")
    assert [e["t"] for e in events].count("say") == 3   # the three deltas, no more


def test_a_tool_block_closing_does_not_close_the_bubble(agent):
    """One text block, one bubble — even with a tool block opening inside it.

    Blocks carry an index and a tool block emits its own start and stop. Going
    by the events alone, the tool's stop ended the text bubble and the rest of
    the answer arrived as a second one. Caught on the real agent, not here.
    """
    channel = agent.subscribe()
    agent.send("hello")
    kinds = [e["t"] for e in drain(channel, "turn")]
    assert kinds.count("say_start") == 1
    assert kinds.count("say_end") == 1


def test_a_second_message_is_refused_while_one_is_running(agent):
    agent.subscribe()
    assert agent.send("hello")[0] == 200
    agent.busy = True
    assert agent.send("again")[0] == 409


def test_the_agent_starts_on_the_first_message_not_before(agent):
    """An idle desk should not hold a second node process inside a 2 GB cap."""
    assert not agent.running()
    agent.subscribe()
    agent.send("hello")
    assert agent.running()


def test_stopping_ends_the_turn_and_keeps_the_session(agent):
    channel = agent.subscribe()
    agent.send("hello")
    drain(channel, "turn")
    agent.busy = True                       # pretend the next turn is running
    assert agent.interrupt()[0] == 200
    end = drain(channel, "turn")[-1]
    assert end["status"] == "stopped"
    assert agent.running()                  # the child survives its own interrupt


def test_stopping_nothing_is_refused(agent):
    agent.subscribe()
    assert agent.interrupt()[0] == 409


@pytest.mark.parametrize("reason", ["aborted_tools", "aborted_streaming"])
def test_every_kind_of_abort_reads_as_stopped(agent, reason):
    """An interrupt comes back as an error result; only the reason tells them apart.

    Measured on the real agent: aborting while a tool runs gives
    `aborted_tools`, aborting while text streams gives `aborted_streaming`.
    Reporting either as a failure would blame the desk for a stop the person
    asked for.
    """
    channel = agent.subscribe()
    agent._translate({
        "type": "result", "subtype": "error_during_execution",
        "is_error": True, "terminal_reason": reason, "result": None,
    })
    assert channel.get(timeout=5) == {"t": "turn", "status": "stopped", "text": ""}


def test_a_genuine_failure_is_still_an_error(agent):
    channel = agent.subscribe()
    agent._translate({
        "type": "result", "subtype": "error_during_execution",
        "is_error": True, "terminal_reason": "completed", "result": "no such tool",
    })
    assert channel.get(timeout=5) == {"t": "turn", "status": "error", "text": "no such tool"}


def test_an_error_result_is_reported_with_its_text(agent):
    channel = agent.subscribe()
    agent.send("boom")
    end = drain(channel, "turn")[-1]
    assert end["status"] == "error"
    assert end["text"] == "something went wrong"


def test_new_session_kills_the_child(agent):
    channel = agent.subscribe()
    agent.send("hello")
    drain(channel, "turn")
    assert agent.running()
    agent.reset()
    assert not agent.running()
    assert any(e["t"] == "reset" for e in _flush(channel))


def test_a_child_that_dies_is_announced(agent, tmp_path):
    """Otherwise the composer sits there accepting messages into nothing."""
    quitter = tmp_path / "quitter.py"
    quitter.write_text("import sys\n", encoding="utf-8")
    agent.command = [sys.executable, "-u", str(quitter)]
    channel = agent.subscribe()
    agent.send("hello")
    assert any(e["t"] == "gone" for e in drain(channel, "gone"))


def _flush(channel):
    out = []
    while True:
        try:
            out.append(channel.get_nowait())
        except queue.Empty:
            return out


# ── Tool pills ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,args,expected", [
    ("Bash", {"command": "ls -la /work", "description": "list"}, "ls -la /work"),
    ("Read", {"file_path": "/work/in/a.xlsx"}, "/work/in/a.xlsx"),
    ("WebFetch", {"url": "https://example.com", "prompt": "x"}, "https://example.com"),
    ("Grep", {"pattern": "TODO", "path": "/work"}, "TODO"),
    ("Odd", {"thing": "  spaced   out  "}, "spaced out"),
    ("Empty", {}, ""),
    ("NotADict", "string", ""),
])
def test_tool_detail_picks_the_useful_argument(name, args, expected):
    assert chat.tool_detail(name, args) == expected


def test_tool_detail_is_clipped():
    assert len(chat.tool_detail("Bash", {"command": "x" * 500})) == chat.TOOL_DETAIL


# ── Fan-out ───────────────────────────────────────────────────────────────
def test_two_pages_both_see_the_turn(agent):
    """The desk is one screen, but a reload leaves the old stream draining."""
    a, b = agent.subscribe(), agent.subscribe()
    agent.send("hello")
    assert drain(a, "turn")[-1]["status"] == "done"
    assert drain(b, "turn")[-1]["status"] == "done"


def test_a_subscriber_that_stopped_reading_does_not_block_the_rest(agent):
    slow = agent.subscribe()
    for _ in range(chat.QUEUE_DEPTH + 50):
        agent.emit(t="say", text="x")
    live = agent.subscribe()
    agent.emit(t="turn", status="done", text="")
    assert live.get(timeout=5)["t"] == "turn"
    assert slow.qsize() == chat.QUEUE_DEPTH


def _fake_proc():
    """Stands in for Popen where only the writing half matters.

    It carries a stdin because the real one always does (the child is spawned
    with stdin=PIPE), and the fixture's teardown closes it.
    """
    return type("P", (), {
        "poll": lambda self: None,
        "stdin": io.StringIO(),
        "wait": lambda self, timeout=None: 0,
        "kill": lambda self: None,
    })()


# ── The command it actually runs ──────────────────────────────────────────
def test_the_real_command_asks_for_the_protocol_this_code_parses():
    assert "--input-format" in chat.COMMAND
    assert chat.COMMAND[chat.COMMAND.index("--input-format") + 1] == "stream-json"
    assert chat.COMMAND[chat.COMMAND.index("--output-format") + 1] == "stream-json"
    # --verbose is required alongside stream-json output, and the partial
    # messages are what make a bubble fill in rather than appear at once.
    assert "--verbose" in chat.COMMAND
    assert "--include-partial-messages" in chat.COMMAND
    # The shell alias carries this flag for the terminal; a child spawned
    # straight from the binary has to pass it itself.
    assert "--dangerously-skip-permissions" in chat.COMMAND


def test_send_serialises_what_the_agent_expects(agent):
    """A plain string content, which is what the protocol takes for a user turn."""
    sent = []
    agent.proc = _fake_proc()
    agent._write = lambda payload: (sent.append(payload), True)[1]
    agent.send("สวัสดี")
    assert sent == [{"type": "user", "message": {"role": "user", "content": "สวัสดี"}}]
    assert json.dumps(sent[0])          # round-trips


def test_interrupt_sends_a_control_request_not_a_signal(agent):
    sent = []
    agent.proc = _fake_proc()
    agent.busy = True
    agent._write = lambda payload: (sent.append(payload), True)[1]
    agent.interrupt()
    assert sent[0]["type"] == "control_request"
    assert sent[0]["request"] == {"subtype": "interrupt"}
    assert sent[0]["request_id"]
