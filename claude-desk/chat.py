#!/usr/bin/env python3
"""Chat side of the desk: Claude Code as bubbles instead of a terminal.

    GET  /chat/events   server-sent events: what the agent is saying and doing
    POST /chat/send     {"text": "..."} — one message to the agent
    POST /chat/stop     interrupt the turn in progress
    POST /chat/new      throw the session away and start another

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
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CWD = os.environ.get("CHAT_CWD", "/work")
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
TOOL_DETAIL = 90        # characters of tool argument shown on a pill


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
        with self.subscribers_lock:
            channels = list(self.subscribers)
        for channel in channels:
            try:
                channel.put_nowait(event)
            except queue.Full:
                # A page that stopped reading is a page that went away; the
                # socket write will fail and clean it up on its own.
                pass

    # ── lifecycle ─────────────────────────────────────────────────────────
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        """Spawn the child. Caller holds the lock."""
        self.proc = subprocess.Popen(
            self.command,
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
    def send(self, text: str) -> tuple:
        with self.lock:
            if self.busy:
                return 409, "still working"
            if not self.running():
                self.start()
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

    def reset(self) -> tuple:
        with self.lock:
            self.stop_child()
        self.emit(t="reset")
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
                    self.emit(t="say_start")
            elif inner_type == "content_block_delta":
                delta = inner.get("delta") or {}
                if (
                    delta.get("type") == "text_delta"
                    and delta.get("text")
                    and index in self.text_blocks
                ):
                    self.emit(t="say", text=delta["text"])
            elif inner_type == "content_block_stop" and index in self.text_blocks:
                self.text_blocks.discard(index)
                self.emit(t="say_end")
            return

        if kind == "assistant":
            # Tool calls are taken from the finished message: the streamed form
            # is input_json_delta, a half-parsed argument object that would
            # have to be reassembled to say anything useful on a pill.
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self.emit(
                        t="tool",
                        name=block.get("name") or "tool",
                        detail=tool_detail(block.get("name") or "", block.get("input")),
                    )
            return

        if kind == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    self.emit(t="tool_done", ok=not block.get("is_error"))
            return

        if kind == "result":
            with self.lock:
                self.busy = False
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
                # Only carried for the cases the page has to explain; a normal
                # answer was already streamed as deltas.
                text="" if status == "done" else str(event.get("result") or ""),
            )
            self.emit(t="busy", on=False)


AGENT = Agent()


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-desk-chat/1"
    # Keep-alive, so the SSE response can stream without a Content-Length.
    protocol_version = "HTTP/1.1"

    def _reply(self, code: int, body: str = ""):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/chat/state":
            # What the composer needs after a reconnect: a page that came back
            # to a turn already in progress should show the stop button, not
            # an idle send button.
            body = json.dumps({"busy": AGENT.busy, "running": AGENT.running()})
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
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

        channel = AGENT.subscribe()
        try:
            self._push({"t": "busy", "on": AGENT.busy})
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
            AGENT.unsubscribe(channel)

    def _push(self, event: dict) -> None:
        self.wfile.write(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n")
        self.wfile.flush()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/chat/send":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(length, 1 << 20)) or b"{}")
            except ValueError:
                self._reply(400, "bad json")
                return
            text = str(body.get("text") or "").strip()
            if not text:
                self._reply(400, "empty")
                return
            code, message = AGENT.send(text)
        elif path == "/chat/stop":
            code, message = AGENT.interrupt()
        elif path == "/chat/new":
            code, message = AGENT.reset()
        else:
            self._reply(404, "not here")
            return
        self._reply(code, message)

    def log_message(self, fmt, *args):
        sys.stderr.write("[chat] %s %s\n" % (self.command, fmt % args))


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
