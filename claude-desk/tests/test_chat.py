"""The chat backend, driven by a fake agent that speaks the same protocol.

The real thing is Claude Code with `--input-format stream-json`; the shapes
here were captured from it (2.1.273) rather than guessed. Using a scripted
child means the whole translation can be exercised without spending a
subscription turn on every run.
"""
import http.client
import io
import json
import queue
import sys
import textwrap
import threading
import time

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
    assert events[-1]["t"] == "turn"
    assert events[-1]["status"] == "done"
    assert events[-1]["text"] == ""


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
    end = channel.get(timeout=5)
    assert (end["t"], end["status"], end["text"]) == ("turn", "stopped", "")


def test_a_genuine_failure_is_still_an_error(agent):
    channel = agent.subscribe()
    agent._translate({
        "type": "result", "subtype": "error_during_execution",
        "is_error": True, "terminal_reason": "completed", "result": "no such tool",
    })
    end = channel.get(timeout=5)
    assert (end["status"], end["text"]) == ("error", "no such tool")


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


# ── Cost and tokens ───────────────────────────────────────────────────────
# Measured on the real agent: total_cost_usd is the **session** running total
# (three turns came back 0.0607 → 0.0701 → 0.1049, never decreasing), while
# `usage` is per turn. Charging a turn the raw total would bill the whole
# session again on every answer.
def test_a_turn_is_charged_the_difference_not_the_running_total(agent):
    channel = agent.subscribe()
    for total in (0.0607, 0.0701, 0.1049):
        agent._translate({"type": "result", "subtype": "success", "is_error": False,
                          "terminal_reason": "completed", "result": "",
                          "total_cost_usd": total,
                          "usage": {"output_tokens": 3, "input_tokens": 2,
                                    "cache_read_input_tokens": 12673,
                                    "cache_creation_input_tokens": 5327},
                          "duration_ms": 4120})
    turns = [e for e in _flush(channel) if e["t"] == "turn"]
    assert [round(t["cost"], 4) for t in turns] == [0.0607, 0.0094, 0.0348]
    assert [t["total"] for t in turns] == [0.0607, 0.0701, 0.1049]


def test_context_is_every_input_token_the_turn_paid_for(agent):
    channel = agent.subscribe()
    agent._translate({"type": "result", "subtype": "success", "is_error": False,
                      "terminal_reason": "completed", "result": "",
                      "total_cost_usd": 1.0,
                      "usage": {"input_tokens": 2, "cache_read_input_tokens": 18000,
                                "cache_creation_input_tokens": 37,
                                "output_tokens": 1011},
                      "duration_ms": 12064})
    turn = channel.get(timeout=5)
    assert turn["context"] == 18039
    assert turn["out"] == 1011
    assert turn["ms"] == 12064


def test_a_result_without_cost_does_not_invent_one(agent):
    channel = agent.subscribe()
    agent._translate({"type": "result", "subtype": "success", "is_error": False,
                      "terminal_reason": "completed", "result": ""})
    turn = channel.get(timeout=5)
    assert turn["cost"] is None
    assert turn["context"] == 0


def test_the_running_total_restarts_with_the_session(agent):
    agent.subscribe()
    agent._translate({"type": "result", "subtype": "success", "is_error": False,
                      "terminal_reason": "completed", "total_cost_usd": 5.0, "result": ""})
    assert agent.spent == 5.0
    agent.reset()
    assert agent.spent == 0.0


# ── Which session this is ─────────────────────────────────────────────────
def test_the_session_id_comes_from_the_agent(agent):
    """The page reloads a conversation's transcript from it."""
    agent.subscribe()
    agent._translate({"type": "system", "subtype": "init",
                      "session_id": "f763ee82-7025-443b-bbf0-42227badf2f0"})
    assert agent.session_id == "f763ee82-7025-443b-bbf0-42227badf2f0"


def test_resuming_puts_the_id_on_the_command_line(agent, monkeypatch):
    started = []
    monkeypatch.setattr(chat.subprocess, "Popen",
                        lambda cmd, **kw: started.append(cmd) or _DeadProc())
    agent.reset(resume="f763ee82-7025-443b-bbf0-42227badf2f0")
    assert started[0][-2:] == ["--resume", "f763ee82-7025-443b-bbf0-42227badf2f0"]


def test_a_plain_reset_carries_no_resume_flag(agent, monkeypatch):
    started = []
    monkeypatch.setattr(chat.subprocess, "Popen",
                        lambda cmd, **kw: started.append(cmd) or _DeadProc())
    agent.reset()
    # Nothing spawns until the first message — an idle desk holds no agent.
    assert started == []


class _DeadProc:
    def poll(self): return None
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
    def wait(self, timeout=None): return 0
    def kill(self): pass


# ── Replaying a past conversation ─────────────────────────────────────────
# The agent replays nothing on --resume, so the earlier messages come from
# the transcript Claude Code writes. Same reader repaints after a reload.
@pytest.fixture
def transcripts(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "SESSION_DIR", str(tmp_path))
    return tmp_path


def write_session(folder, name, records):
    (folder / (name + ".jsonl")).write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def test_a_transcript_replays_as_the_page_renders_it(transcripts):
    write_session(transcripts, "s", [
        {"type": "user", "message": {"content": "ทำ slide ให้หน่อย"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/work/in/a.xlsx"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "ok", "is_error": False}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "เสร็จแล้ว"}]}},
    ])
    assert chat.transcript("s") == [
        {"k": "you", "text": "ทำ slide ให้หน่อย"},
        {"k": "tool", "name": "Read", "detail": "/work/in/a.xlsx"},
        {"k": "tool_done", "ok": True},
        {"k": "claude", "text": "เสร็จแล้ว"},
    ]


def test_replayed_slash_commands_are_not_shown_as_things_you_typed(transcripts):
    write_session(transcripts, "s", [
        {"type": "user", "message": {"content": "<local-command-caveat>…</local-command-caveat>"}},
        {"type": "user", "message": {"content": "the real question"}},
    ])
    assert chat.transcript("s") == [{"k": "you", "text": "the real question"}]


def test_only_the_tail_of_a_long_conversation_is_kept(transcripts, monkeypatch):
    monkeypatch.setattr(chat, "HISTORY_ITEMS", 3)
    write_session(transcripts, "s", [
        {"type": "user", "message": {"content": str(i)} } for i in range(10)])
    assert [i["text"] for i in chat.transcript("s")] == ["7", "8", "9"]


def test_a_huge_transcript_is_bounded(transcripts, monkeypatch):
    """One of these files is 4.6 MB and a single record can be megabytes."""
    monkeypatch.setattr(chat, "HISTORY_BUDGET", 64 * 1024)
    path = transcripts / "s.jsonl"
    path.write_text(
        json.dumps({"type": "file-history-snapshot", "blob": "z" * 3_000_000}) + "\n"
        + json.dumps({"type": "user", "message": {"content": "after the wall"}}) + "\n",
        encoding="utf-8")
    assert chat.transcript("s") == []


def test_a_missing_transcript_is_empty_not_an_error(transcripts):
    assert chat.transcript("nope") == []


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


# ── Coming back after a drop ──────────────────────────────────────────────
# A phone loses this stream constantly: iOS suspends a backgrounded PWA, so
# reconnecting in the middle of an answer is the ordinary case rather than an
# edge one. Every event is numbered for that reason.

def test_every_event_is_numbered_in_order(agent):
    channel = agent.subscribe()
    assert agent.send("hello")[0] == 200
    events = drain(channel, "turn")
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_a_page_that_missed_events_is_given_exactly_those(agent):
    channel = agent.subscribe()
    assert agent.send("hello")[0] == 200
    events = drain(channel, "turn")

    # Pretend the page applied the first three and then the phone slept. The
    # ring is the authority, not what this test drained — the turn ends with a
    # `busy` event after the one drain stops on.
    pivot = events[2]["seq"]
    missed = agent.since(pivot)
    assert [e["seq"] for e in missed] == [e["seq"] for e in agent.ring if e["seq"] > pivot]
    # And a page that missed nothing is sent nothing.
    assert agent.since(agent.seq) == []


def test_a_page_too_far_behind_is_told_to_repaint(agent):
    channel = agent.subscribe()
    assert agent.send("hello")[0] == 200
    drain(channel, "turn")
    # The ring has rolled past what this page last saw.
    agent.ring.clear()
    assert agent.since(1) is None


# The bookkeeping behind a snapshot is driven straight through the translator:
# the fake agent finishes a turn in milliseconds, so asking it to hold still
# mid-answer is a race, and what matters here is which events leave which
# residue rather than how fast a child runs.
def _block_start(agent, index, kind="text"):
    agent._translate({"type": "stream_event", "event": {
        "type": "content_block_start", "index": index,
        "content_block": {"type": kind}}})


def _delta(agent, index, text):
    agent._translate({"type": "stream_event", "event": {
        "type": "content_block_delta", "index": index,
        "delta": {"type": "text_delta", "text": text}}})


def _block_stop(agent, index):
    agent._translate({"type": "stream_event", "event": {
        "type": "content_block_stop", "index": index}})


def test_the_snapshot_carries_only_what_the_transcript_lacks():
    """The half-said answer and the tools still running, and nothing else.

    Everything that finished is already in the file the page reads; sending it
    here as well would draw every message twice.
    """
    agent = chat.Agent()
    _block_start(agent, 0)
    _delta(agent, 0, "กำลัง")
    _delta(agent, 0, "ทำอยู่")

    snap = agent.snapshot()
    assert snap["t"] == "resync"
    assert snap["partial"] == "กำลังทำอยู่"
    assert snap["tools"] == []
    assert snap["seq"] == agent.seq

    _block_stop(agent, 0)
    # Said in full, so Claude Code has written it: the transcript is where a
    # page gets it back, and repeating it here would double it.
    assert agent.snapshot()["partial"] == ""


def test_a_tool_still_running_is_in_the_snapshot():
    agent = chat.Agent()
    agent._translate({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}]}})
    assert agent.snapshot()["tools"] == [{"name": "Bash", "detail": "echo hi"}]

    agent._translate({"type": "user", "message": {"content": [
        {"type": "tool_result", "is_error": False}]}})
    assert agent.snapshot()["tools"] == []


def test_a_finished_turn_leaves_nothing_unwritten():
    agent = chat.Agent()
    _block_start(agent, 0)
    _delta(agent, 0, "ครึ่งทาง")
    agent._translate({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}]}})

    agent._translate({"type": "result", "subtype": "success", "is_error": False,
                      "terminal_reason": "completed", "result": ""})
    snap = agent.snapshot()
    assert snap["partial"] == ""
    assert snap["tools"] == []
    assert snap["busy"] is False


# ── The wire, not just the bookkeeping ────────────────────────────────────
def _serve(monkeypatch, agent):
    """The real handler, on a throwaway port, talking to this fake agent."""
    from http.server import ThreadingHTTPServer

    monkeypatch.setattr(chat, "AGENT", agent)
    server = ThreadingHTTPServer(("127.0.0.1", 0), chat.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _frames(response, count, timeout=10):
    """Parse `id:`/`data:` frames off an open SSE response."""
    out = []
    seq = None
    deadline = time.time() + timeout
    while len(out) < count and time.time() < deadline:
        line = response.fp.readline()
        if not line:
            break
        line = line.decode().strip()
        if line.startswith("id:"):
            seq = int(line[3:])
        elif line.startswith("data:"):
            event = json.loads(line[5:])
            event["_id"] = seq
            seq = None
            out.append(event)
    return out


def _subscribe(server, headers=None, path="/chat/events"):
    conn = http.client.HTTPConnection(*server.server_address, timeout=10)
    conn.request("GET", path, headers=headers or {})
    response = conn.getresponse()
    assert response.status == 200
    return conn, response


def test_the_stream_numbers_its_events_on_the_wire(monkeypatch, agent):
    server = _serve(monkeypatch, agent)
    try:
        conn, response = _subscribe(server)
        events = _frames(response, 1)          # the composer's state, first
        assert agent.send("hello")[0] == 200
        events += _frames(response, 3)
        # The first frame is the composer's state and carries no id; every
        # event of the turn does, and it is the seq the page counts with.
        numbered = [e for e in events if e["_id"] is not None]
        assert numbered, events
        assert all(e["_id"] == e["seq"] for e in numbered)
        conn.close()
    finally:
        server.shutdown()


def test_a_reconnect_replays_what_the_page_missed(monkeypatch, agent):
    server = _serve(monkeypatch, agent)
    try:
        channel = agent.subscribe()
        assert agent.send("hello")[0] == 200
        drain(channel, "turn")

        # A phone that slept after the third event and came back: EventSource
        # sends the last id it saw as a header, without being asked.
        pivot = agent.ring[2]["seq"]
        expected = [e["seq"] for e in agent.ring if e["seq"] > pivot]
        conn, response = _subscribe(server, {"Last-Event-ID": str(pivot)})
        events = _frames(response, 1 + len(expected))
        assert [e["seq"] for e in events if "seq" in e] == expected
        conn.close()
    finally:
        server.shutdown()


def test_a_reconnect_too_far_behind_is_sent_a_snapshot(monkeypatch, agent):
    server = _serve(monkeypatch, agent)
    try:
        channel = agent.subscribe()
        assert agent.send("hello")[0] == 200
        drain(channel, "turn")
        agent.ring.clear()

        conn, response = _subscribe(server, path="/chat/events?after=1")
        events = _frames(response, 2)
        resync = next(e for e in events if e["t"] == "resync")
        assert resync["seq"] == agent.seq
        assert resync["partial"] == ""
        conn.close()
    finally:
        server.shutdown()
