#!/usr/bin/env python3
"""Chat side of the desk: Claude Code as bubbles instead of a terminal.

    GET  /chat/events   server-sent events: what the agent is saying and doing
    POST /chat/send     {"text": "..."} — one message to the agent
    POST /chat/stop     interrupt the turn in progress
    POST /chat/new      throw the session away, or open a past one
    GET  /chat/state    is a turn in flight, and which session this is
    GET  /chat/history  a past conversation, rendered like the live stream

Runs in the desk container next to ttyd and upload.py, on port 7683, reachable
only through the nginx sidecar and its basic auth.

This does not wrap the terminal. It drives a **second** Claude Code, started
with `--input-format stream-json --output-format stream-json`, which is a
documented protocol rather than a screen to scrape: the alternative — parsing
ANSI out of the terminal the page already has — breaks every time Claude Code
changes how it draws. The terminal view is untouched and stays the only way to
reach `mimo`, `ask` and a shell, none of which speak this protocol.

Why a chat view at all, when there is a perfectly good terminal: a terminal
wraps hard at COLUMNS. On a phone that is about 40 columns of Thai, and long
answers are painful to read. Bubbles reflow.

Two agents can therefore be working in /work at once — the one in tmux and
this one. That is a real change from "one agent at a time" and it is not
prevented here, because the pane reports `claude` whenever a session is merely
*open*, so refusing on that would block the normal case. The page says when
both are up and leaves the judgement to the person holding the phone.

The child gets --dangerously-skip-permissions for the same reason the shell
alias does: every tool call would otherwise need a tap, and the container is
the sandbox.

CHAT_CWD, CHAT_PORT and CHAT_COMMAND exist so this can be run and tested
outside the container.
"""
import collections
import codex_backend
import agent_options
import usage_status
import workspace_api
import deploy_bridge
import json
import os
import queue
import shlex
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CWD = os.environ.get("CHAT_CWD", "/work")
HOME = os.environ.get("HOME", "/home/claude")
# Same directory upload.py lists for the sessions sheet: Claude Code names a
# project folder after its cwd with the separators replaced.
SESSION_DIR = os.environ.get(
    "DESK_SESSION_DIR", os.path.join(HOME, ".claude", "projects", "-work")
)
PORT = int(os.environ.get("CHAT_PORT", "7683"))

# Overridable so a test can put a scripted child here instead of the real
# agent — the protocol is the interface, and a fake that speaks it exercises
# everything below without spending a subscription turn.
COMMAND = shlex.split(os.environ.get("CHAT_COMMAND", "")) or [
    "claude",
    "--print",
    "--input-format", "stream-json",
    "--output-format", "stream-json",
    "--include-partial-messages",   # token-by-token text, so a bubble fills in
    "--verbose",                    # required for stream-json output
    "--dangerously-skip-permissions",
]

HEARTBEAT = 20          # seconds between SSE comment lines
QUEUE_DEPTH = 2000      # events held for a subscriber that stopped reading
# Events kept for a page that comes back. iOS suspends a backgrounded PWA, so
# a phone reconnects constantly and mid-turn — it is the ordinary case, not an
# edge one. A long answer is a few thousand deltas; past that the page is sent
# a snapshot instead, which costs one transcript read rather than a wrong view.
RING = 4000
TOOL_DETAIL = 90        # characters of tool argument shown on a pill
HISTORY_ITEMS = 300     # bubbles and pills kept from a past conversation
HISTORY_BUDGET = 8 << 20  # bytes read from one transcript
MAX_LINE = 64 << 10     # one record can be megabytes; readline(size) bounds it
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def tool_detail(name: str, args) -> str:
    """The one line worth showing on a tool pill.

    Claude Code's own transcript shows a command or a path, not the whole
    argument object, and on a phone there is room for about that much.
    """
    if not isinstance(args, dict):
        return ""
    # Order matters: for a search it is the pattern that says what is going on,
    # not the directory it ran in, and both are present.
    for key in ("command", "file_path", "pattern", "url", "path", "query", "prompt"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:TOOL_DETAIL]
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:TOOL_DETAIL]
    return ""


def session_directory(cwd=None):
    if cwd is None or cwd == CWD:
        return SESSION_DIR
    # Claude uses non-alphanumeric cwd characters as separators.
    return os.path.join(HOME, '.claude', 'projects', re.sub(r'[^a-zA-Z0-9]', '-', cwd))


def session_exists(session_id, cwd):
    return bool(UUID.fullmatch(session_id)) and os.path.isfile(
        os.path.join(session_directory(cwd), session_id + '.jsonl'))


def workspace_sessions(cwd):
    # Reuse the bounded title reader without the document session directory.
    from upload import title_of
    found = []
    try:
        with os.scandir(session_directory(cwd)) as entries:
            for entry in entries:
                if not entry.name.endswith('.jsonl') or not UUID.fullmatch(entry.name[:-6]):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                st = entry.stat()
                found.append({'id': entry.name[:-6], 'title': title_of(entry.path),
                              'mtime': st.st_mtime, 'size': st.st_size})
    except OSError:
        pass
    return sorted(found, key=lambda item: item['mtime'], reverse=True)[:50]


def transcript(session_id: str, cwd=None) -> list:
    """A past conversation, in the same shapes the live stream emits.

    Claude Code writes every session to `~/.claude/projects/-work/<id>.jsonl`,
    so this is where a resumed conversation's earlier messages come from — the
    agent replays nothing on `--resume`, it just knows the context. It also
    covers a plain reload: nothing is kept in memory here, and re-reading the
    file is both simpler and more honest than a transcript this process would
    have to keep in step with what the page renders.

    Bounded the same way the session list is: one of these files is 4.6 MB,
    and a single `file-history-snapshot` record can be megabytes on its own.
    Only the tail is kept — that is the part of a long conversation anyone
    scrolls back to.
    """
    path = os.path.join(session_directory(cwd), session_id + ".jsonl")
    items = collections.deque(maxlen=HISTORY_ITEMS)
    read = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            while read < HISTORY_BUDGET:
                line = handle.readline(MAX_LINE)
                if not line:
                    break
                read += len(line)
                try:
                    record = json.loads(line)
                except ValueError:
                    continue            # a line clipped at MAX_LINE lands here
                if not isinstance(record, dict):
                    continue
                items.extend(_replay(record))
    except OSError:
        return []
    return list(items)


def _replay(record: dict) -> list:
    """The renderable parts of one transcript record."""
    kind = record.get("type")
    content = (record.get("message") or {}).get("content")
    out = []

    if kind == "user":
        if isinstance(content, str):
            text = " ".join(content.split())
            # Replayed slash commands and other bookkeeping arrive as user
            # records wrapped in angle brackets; nobody typed them.
            return [{"k": "you", "text": content}] if text and not text.startswith("<") else []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                out.append({"k": "tool_done", "ok": not block.get("is_error")})
            elif block.get("type") == "text":
                text = block.get("text") or ""
                if text.strip() and not text.strip().startswith("<"):
                    out.append({"k": "you", "text": text})
        return out

    if kind == "assistant":
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and (block.get("text") or "").strip():
                out.append({"k": "claude", "text": block["text"]})
            elif block.get("type") == "tool_use":
                out.append({
                    "k": "tool",
                    "name": block.get("name") or "tool",
                    "detail": tool_detail(block.get("name") or "", block.get("input")),
                })
    return out


class Agent:
    """One Claude Code child, and a fan-out of what it says.

    Started on the first message rather than at boot: an idle desk should not
    be holding a second node process open inside a 2 GB cap.
    """

    def __init__(self, command=None, cwd=None):
        self.command = command or COMMAND
        self.cwd = cwd or CWD
        self.proc = None
        self.busy = False
        self.lock = threading.Lock()
        self.subscribers = set()
        self.subscribers_lock = threading.Lock()
        # Indexes of the content blocks that hold text. A message interleaves
        # text and tool_use blocks, and they all emit start/stop with an
        # index — without this, a tool block's stop closed the bubble a text
        # block was still filling, and the answer arrived split in two.
        self.text_blocks = set()
        self.session_id = None
        self.model = ""
        self.effort = ""
        # Running total the agent reports, kept so each turn can be charged
        # the difference (see the result branch).
        self.spent = 0.0
        # Everything said, numbered, so a page that dropped the connection can
        # ask for what it missed instead of silently losing the middle of an
        # answer. `partial` and `open_tools` are what is *not* in the
        # transcript yet — Claude Code writes a message when it completes — and
        # together with the transcript they are a whole view of the turn.
        self.seq = 0
        self.ring = collections.deque(maxlen=RING)
        self.partial = ""
        self.open_tools = []

    # ── fan-out ───────────────────────────────────────────────────────────
    def subscribe(self) -> queue.Queue:
        channel = queue.Queue(maxsize=QUEUE_DEPTH)
        with self.subscribers_lock:
            self.subscribers.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self.subscribers_lock:
            self.subscribers.discard(channel)

    def emit(self, **event) -> None:
        # The same lock covers the numbering and the ring: an event's seq and
        # its place in the replay have to agree, or a reconnect gets them out
        # of order.
        with self.subscribers_lock:
            self.seq += 1
            event["seq"] = self.seq
            self.ring.append(event)
            channels = list(self.subscribers)
        for channel in channels:
            try:
                channel.put_nowait(event)
            except queue.Full:
                # A page that stopped reading is a page that went away; the
                # socket write will fail and clean it up on its own.
                pass

    def since(self, after: int):
        """Events the page missed, or None when they are no longer held.

        None is not a failure — it means "repaint from `snapshot()`", which is
        cheap and always right.
        """
        with self.subscribers_lock:
            if after >= self.seq:
                return []                       # nothing missed
            if after <= 0:
                # A page that has applied nothing is not behind, it is new.
                # Replaying from the first event would draw every past turn of
                # this process on top of the transcript it already reads.
                return None
            if not self.ring or self.ring[0]["seq"] > after + 1:
                return None                     # rolled past; too old to patch
            return [e for e in self.ring if e["seq"] > after]

    def snapshot(self) -> dict:
        """Everything a page needs to draw the turn it came back to.

        Deliberately *not* the whole conversation: the finished messages are in
        the transcript the page already reads, and sending them here too would
        draw each of them twice.
        """
        with self.subscribers_lock:
            return {
                "t": "resync",
                "seq": self.seq,
                # A hint, not a guarantee: `busy` is written under the other
                # lock. The page is told again by the `busy` events either way.
                "busy": self.busy,
                "session_id": self.session_id or "",
                "partial": self.partial,
                "tools": list(self.open_tools),
            }

    # ── lifecycle ─────────────────────────────────────────────────────────
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, resume: str = "") -> None:
        """Spawn the child. Caller holds the lock."""
        self.session_id = resume or None
        self.spent = 0.0
        self.proc = subprocess.Popen(
            self.command + (["--model", self.model] if self.model else [])
            + (["--effort", self.effort] if self.effort else [])
            + (["--resume", resume] if resume else []),
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def stop_child(self) -> None:
        """Caller holds the lock."""
        proc, self.proc = self.proc, None
        self.busy = False
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _write(self, payload: dict) -> bool:
        """Caller holds the lock."""
        if not self.running():
            return False
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    # ── the three things the page can do ──────────────────────────────────
    def send(self, text: str, model=None, effort=None) -> tuple:
        with self.lock:
            if self.busy:
                return 409, "still working"
            model = self.model if model is None else model
            effort = self.effort if effort is None else effort
            changed = (model, effort) != (self.model, self.effort)
            self.model, self.effort = model, effort
            if changed and self.running():
                resume = self.session_id or ""
                self.stop_child()
                self.start(resume=resume)
            if not self.running():
                self.start(resume=self.session_id or "")
            ok = self._write({
                "type": "user",
                "message": {"role": "user", "content": text},
            })
            if not ok:
                return 503, "agent not accepting input"
            self.busy = True
        self.emit(t="busy", on=True)
        return 200, "ok"

    def interrupt(self) -> tuple:
        """Stop the turn without losing the session.

        A control request rather than a signal: the child answers it in about
        a second, ends the turn as aborted, and stays up for the next message
        (verified against 2.1.273).
        """
        with self.lock:
            if not self.running() or not self.busy:
                return 409, "nothing running"
            ok = self._write({
                "type": "control_request",
                "request_id": "stop-%d" % time.time_ns(),
                "request": {"subtype": "interrupt"},
            })
        return (200, "ok") if ok else (503, "could not interrupt")

    def reset(self, resume: str = "") -> tuple:
        """Throw the current session away; optionally open a past one instead.

        Resuming here rather than in the terminal is the point: the sessions
        sheet used to only ever type into the tmux pane, so from the chat view
        tapping a past conversation brought it back *in the other view*.

        Refused mid-turn. The terminal has a desk per person but chat is one
        process with one child, so this button is reachable by either of us:
        without the guard, opening a past conversation would kill an answer
        the other person is waiting on and send them a `reset` they did not
        ask for. Stop first, then open — that path is one tap away.
        """
        with self.lock:
            if self.busy:
                return 409, "still working"
            if resume and not session_exists(resume, self.cwd):
                return 404, "Session not found in this workspace"
            self.stop_child()
            self.session_id = resume or None
            self.spent = 0.0
            # A new session owes nothing from the old one's turn.
            self.partial = ""
            self.open_tools = []
            if resume:
                # Started now rather than on the first message, so a failed
                # --resume is reported while the sheet is still open.
                self.start(resume=resume)
                if not self.running():
                    return 503, "could not resume"
        self.emit(t="reset", session_id=resume or "")
        self.emit(t="busy", on=False)
        return 200, "ok"

    # ── reading the child ─────────────────────────────────────────────────
    def _read(self, proc) -> None:
        """Translate the agent's protocol into the few events the page needs.

        Deliberately not a passthrough. The page renders bubbles and pills, and
        keeping the translation here means Claude Code's protocol can grow
        without the browser bundle having to learn about it.
        """
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            try:
                self._translate(event)
            except Exception:  # noqa: BLE001 - one bad event must not end the stream
                continue
        # stdout closed: the child is gone, whatever the reason.
        with self.lock:
            if proc is self.proc:
                self.proc = None
                self.busy = False
        self.emit(t="busy", on=False)
        self.emit(t="gone")

    def _translate(self, event: dict) -> None:
        kind = event.get("type")

        if kind == "rate_limit_event":
            data = usage_status.record_claude(event.get("rate_limit_info"))
            if data:
                self.emit(t="quota", data=data)
            return

        if kind == "stream_event":
            inner = event.get("event") or {}
            inner_type = inner.get("type")
            # Text arrives twice — once as deltas, once in the finished
            # assistant message. The deltas are what make a bubble fill in, so
            # they are the ones rendered, and the finished copy is ignored.
            index = inner.get("index")
            if inner_type == "message_start":
                self.text_blocks.clear()
            elif inner_type == "content_block_start":
                if (inner.get("content_block") or {}).get("type") == "text":
                    self.text_blocks.add(index)
                    self.partial = ""
                    self.emit(t="say_start")
            elif inner_type == "content_block_delta":
                delta = inner.get("delta") or {}
                if (
                    delta.get("type") == "text_delta"
                    and delta.get("text")
                    and index in self.text_blocks
                ):
                    self.partial += delta["text"]
                    self.emit(t="say", text=delta["text"])
            elif inner_type == "content_block_stop" and index in self.text_blocks:
                self.text_blocks.discard(index)
                # Complete, so it is in the transcript now; a page that comes
                # back reads it from there rather than from the snapshot.
                self.partial = ""
                self.emit(t="say_end")
            return

        if kind == "assistant":
            # Tool calls are taken from the finished message: the streamed form
            # is input_json_delta, a half-parsed argument object that would
            # have to be reassembled to say anything useful on a pill.
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name") or "tool"
                    detail = tool_detail(name, block.get("input"))
                    self.open_tools.append({"name": name, "detail": detail})
                    self.emit(t="tool", name=name, detail=detail)
            return

        if kind == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    # Tools finish in the order they started, which is what the
                    # page relies on to match a result to its pill.
                    if self.open_tools:
                        self.open_tools.pop(0)
                    self.emit(t="tool_done", ok=not block.get("is_error"))
            return

        if kind == "system" and event.get("subtype") == "init":
            # Re-sent every turn, same id. Knowing it is what lets the page
            # paint this conversation's transcript after a reload.
            self.session_id = event.get("session_id") or self.session_id
            return

        if kind == "result":
            with self.lock:
                self.busy = False
            # Nothing of this turn is unwritten any more.
            self.partial = ""
            self.open_tools = []
            # `total_cost_usd` is the **session** total, measured: three turns
            # came back 0.0607 → 0.0701 → 0.1049, never decreasing. What the
            # turn cost is therefore the difference, and the running total is
            # worth showing too. `usage`, by contrast, is per turn.
            total = event.get("total_cost_usd")
            cost = None
            if isinstance(total, (int, float)):
                cost = max(total - self.spent, 0)
                self.spent = total
            usage = event.get("usage") or {}
            context = sum(
                usage.get(k) or 0
                for k in ("input_tokens", "cache_read_input_tokens",
                          "cache_creation_input_tokens")
            )
            # An interrupt comes back as an error result, and the only thing
            # that tells it apart from a real failure is the reason: measured
            # as `aborted_tools` when a tool was running and
            # `aborted_streaming` when text was, so the prefix is the test.
            # Calling a stop the user asked for "ทำงานไม่สำเร็จ" would be a lie.
            reason = str(event.get("terminal_reason") or "")
            if reason.startswith("aborted"):
                status = "stopped"
            elif event.get("is_error"):
                status = "error"
            else:
                status = "done"
            self.emit(
                t="turn",
                status=status,
                # Why it ended, in the agent's own words. The page shows it
                # under a failure: "ทำงานไม่สำเร็จ" on its own leaves nothing
                # to act on and nothing to report.
                reason=reason or str(event.get("subtype") or ""),
                # Only carried for the cases the page has to explain; a normal
                # answer was already streamed as deltas.
                text="" if status == "done" else str(event.get("result") or ""),
                cost=cost,
                total=total,
                context=context,
                out=usage.get("output_tokens") or 0,
                ms=event.get("duration_ms") or 0,
            )
            self.emit(t="busy", on=False)


class CodexAgent(codex_backend.CodexMixin, Agent):
    pass


AGENT = Agent()
AGENTS = {}
AGENTS_LOCK = threading.Lock()


def agent_for(user, provider, workspace_id="", cwd=None):
    # Legacy/default agent keeps direct integrations compatible. nginx sets
    # the authenticated user; clients cannot choose another user's process.
    if not user and provider == "claude" and not workspace_id:
        return AGENT
    key = (user, provider, workspace_id)
    with AGENTS_LOCK:
        if key not in AGENTS:
            AGENTS[key] = CodexAgent(cwd=cwd) if provider == "codex" else Agent(cwd=cwd)
        return AGENTS[key]



class Handler(BaseHTTPRequestHandler):
    server_version = "ai-deck-chat/1"
    # Keep-alive, so the SSE response can stream without a Content-Length.
    protocol_version = "HTTP/1.1"

    def _json_body(self, body: str):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _reply(self, code: int, body: str = ""):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _agent(self):
        provider = parse_qs(urlparse(self.path).query).get("provider", ["claude"])[0]
        if provider not in ("claude", "codex"):
            self._reply(400, "unknown provider")
            return None
        self.provider = provider
        owner = self.headers.get("X-Desk-User", "")
        if workspace_api.enabled():
            from workspaces import WorkspaceError
            try:
                item = workspace_api.workspace(self)
                return agent_for(owner, provider, item['id'], item['path'])
            except WorkspaceError as exc:
                self._reply(exc.status, exc.message)
                return None
            except OSError:
                self._reply(503, "Workspace storage is unavailable")
                return None
        return agent_for(owner, provider)

    def do_GET(self):
        if self.path == '/chat/health':
            self._json_body(json.dumps({'status': 'ready', 'revision': os.environ.get('AI_DECK_BUILD_SHA', 'unknown')}))
            return
        if deploy_bridge.handle(self) or workspace_api.handle(self):
            return
        agent = self._agent()
        if agent is None:
            return
        path = self.path.split("?", 1)[0]
        if path == "/chat/options":
            self._json_body(json.dumps(agent_options.catalog(self.provider)))
            return
        elif path == "/chat/sessions":
            items = codex_backend.sessions(agent.cwd) if self.provider == 'codex' else workspace_sessions(agent.cwd)
            self._json_body(json.dumps({'sessions': items, 'pane': None}))
            return
        elif path == "/chat/state":
            # What the composer needs after a reconnect: a page that came back
            # to a turn already in progress should show the stop button, not
            # an idle send button.
            body = json.dumps({
                "busy": agent.busy,
                "running": agent.running(),
                # The page reloads this conversation's transcript from it.
                "session_id": agent.session_id or "",
                "spent": agent.spent,
                "model": agent.model,
                "effort": agent.effort,
            })
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/chat/history":
            wanted = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            # A uuid or nothing: this becomes a filename.
            if not UUID.match(wanted):
                self._reply(400, "bad id")
                return
            self._json_body(json.dumps({"items": (codex_backend.transcript(wanted, agent.cwd) if self.provider == "codex" else transcript(wanted, agent.cwd))},
                                       ensure_ascii=False))
            return
        if path != "/chat/events":
            self._reply(404, "not here")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        # Belt and braces with nginx's proxy_buffering off: without this a
        # proxy can hold the whole stream and the page shows nothing until the
        # turn ends, which looks exactly like a hung agent.
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # Where the page got to before it lost the connection. EventSource
        # sends the last id it saw back as a header on its own reconnect, and
        # `?after=` covers a page that reopens the stream itself.
        after = self.headers.get("Last-Event-ID")
        if after is None:
            after = parse_qs(urlparse(self.path).query).get("after", [""])[0]
        try:
            after = int(after)
        except (TypeError, ValueError):
            after = None

        channel = agent.subscribe()
        try:
            self._push({"t": "busy", "on": agent.busy})
            if after is not None:
                missed = agent.since(after)
                if missed is None:
                    # Too far behind to patch up. The snapshot plus the
                    # transcript the page reads is a whole view of the turn,
                    # and drawing it again is cheaper than being wrong.
                    self._push(agent.snapshot())
                else:
                    for event in missed:
                        self._push(event)
            while True:
                try:
                    event = channel.get(timeout=HEARTBEAT)
                except queue.Empty:
                    # A comment line: keeps nginx, the DSM reverse proxy and a
                    # dozing phone from deciding the connection is dead.
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._push(event)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass            # the page navigated away or the phone slept
        finally:
            agent.unsubscribe(channel)

    def _push(self, event: dict) -> None:
        # The id is what the browser hands back as Last-Event-ID after a drop.
        # Replayed events keep their own, so a page never applies one twice.
        line = b""
        if isinstance(event.get("seq"), int):
            line = b"id: %d\n" % event["seq"]
        self.wfile.write(
            line + b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n"
        )
        self.wfile.flush()

    def _body(self, limit):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > limit:
                self.close_connection = True
                self._reply(413 if length > limit else 400, "invalid body length")
                return None
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
            return body
        except ValueError:
            self.close_connection = True
            self._reply(400, "bad json")
            return None

    def do_POST(self):
        if deploy_bridge.handle(self) or workspace_api.handle(self):
            return
        agent = self._agent()
        if agent is None:
            return
        path = self.path.split("?", 1)[0]
        body = self._body(1 << 20 if path == "/chat/send" else 4096)
        if body is None:
            return
        if path == "/chat/send":
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                self._reply(400, "text must be a nonempty string")
                return
            model, effort = body.get("model", agent.model), body.get("effort", agent.effort)
            if not agent_options.validate(self.provider, model, effort):
                self._reply(400, "unsupported model or effort; refresh the model list")
                return
            try:
                code, message = agent.send(text.strip(), model=model, effort=effort)
            except OSError:
                self._reply(503, "Agent could not start. Check installation and sign in from Terminal.")
                return
        elif path == "/chat/stop":
            code, message = agent.interrupt()
        elif path == "/chat/new":
            wanted = body.get("id") or ""
            if not isinstance(wanted, str) or (wanted and not UUID.fullmatch(wanted)):
                self._reply(400, "bad id")
                return
            code, message = agent.reset(resume=wanted)
        else:
            self._reply(404, "not here")
            return
        self._reply(code, message)

    def log_message(self, fmt, *args):
        sys.stderr.write("[chat] %s %s\n" % (self.command, fmt % args))


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
