#!/usr/bin/env python3
"""The desk's small HTTP side, for the drawer and the header in the page.

Files (the drawer):

    PUT    /upload/in/<name>    write a source file into <work>/in
    DELETE /upload/<dir>/<name> remove one file from <work>/in or <work>/out
    DELETE /upload/<dir>/       remove every file in that folder

Desk (the header and the sessions sheet):

    GET    /api/status          the rate-limit numbers statusline.sh last saw
    GET    /api/sessions        past Claude Code sessions in /work, newest first
    POST   /api/resume {"id":…} type `claude --resume <id>` into the tmux pane
    POST   /api/new             type `claude` into the tmux pane
    POST   /api/quit            put the pane back at a shell prompt

Runs inside the desk container (which already owns /work) next to ttyd on
port 7682. The nginx sidecar is the only thing that can reach it, and it sits
behind basic auth there; nginx also caps the body size. This process only
enforces which paths are legal.

The two POSTs drive tmux rather than the page's websocket on purpose: keys
sent down the socket land wherever the pane's focus happens to be, and the
pane usually has Claude Code in it — `claude --resume <uuid>` would be typed
into Claude's prompt as a message. So they refuse unless the pane is sitting
at a shell, and the page says so instead of doing something surprising.

Deletes are permanent. DSM's recycle bin is implemented by the file services,
not the filesystem, so os.unlink from a container skips it entirely.

Set WORK_DIR to run it anywhere (used to exercise it outside the container).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, parse_qs, urlparse

import codex_backend
import workspace_api
import shlex
import agent_options
import usage_status

WORK_DIR = os.environ.get("WORK_DIR", "/work")
PORT = int(os.environ.get("UPLOAD_PORT", "7682"))
HOME = os.environ.get("HOME", "/home/claude")

# Claude Code names a project directory after its cwd with the separators
# replaced, so the desk's /work is "-work".
SESSION_DIR = os.environ.get(
    "DESK_SESSION_DIR", os.path.join(HOME, ".claude", "projects", "-work")
)
STATUS_FILE = os.environ.get(
    "DESK_STATUS_FILE", os.path.join(HOME, ".claude", "desk-status.json")
)
DONE_FILE = os.environ.get(
    "DESK_DONE_FILE", os.path.join(HOME, ".claude", "desk-done.json")
)
TMUX_TARGET = os.environ.get("DESK_TMUX_TARGET", "main:0.0")

# One tmux session per person — see entrypoint.sh. This process serves every
# desk, so which session a request drives comes from the basic auth user
# nginx forwards as X-Desk-User. Without that, one person's Quit button would
# put an Escape and a /exit into the other person's running turn.
DESK_USERS = os.environ.get("DESK_USERS", "")


def roster(spec: str) -> dict:
    """'fix:7681,Pook:7684' → {'fix': 'fix:0.0', 'pook': 'pook:0.0'}.

    Keyed by the lowercased user because that is also how entrypoint.sh names
    the session; both sides must sanitise identically or the API drives a
    session nobody is attached to.
    """
    desks = {}
    for entry in spec.split(","):
        user = entry.split(":", 1)[0].strip()
        if not user:
            continue
        session = re.sub(r"[^a-z0-9_-]", "-", user.lower())
        desks[user.lower()] = session + ":0.0"
    return desks


DESKS = roster(DESK_USERS)


def target_for(user: str) -> str:
    """The tmux target for a request, or the default desk.

    An unknown user (no roster, or a basic auth account that predates it)
    lands on the first desk, which is the one ttyd runs as PID 1.
    """
    if not DESKS:
        return TMUX_TARGET
    return DESKS.get((user or "").lower(), next(iter(DESKS.values())))

# The two folders the page knows about. Anything else is a 404: the share
# root holds #recycle and @eaDir, which must never be reachable from here.
DIRS = {"in": os.path.join(WORK_DIR, "in"), "out": os.path.join(WORK_DIR, "out")}

SAFE = re.compile(r"^[^/\\\x00]{1,200}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# What counts as "the pane is free". Anything else — node (Claude Code or
# MiMoCode), vim, less — means a program owns the keyboard.
SHELLS = {"bash", "sh", "zsh", "-bash", "dash"}

QUIT_WAIT = 10              # seconds to wait for the pane to come back to a shell
SESSION_LIMIT = 30          # newest N transcripts; the rest are not findable anyway
TITLE_BUDGET = 256 * 1024   # bytes read per transcript while hunting for a title
MAX_LINE = 64 * 1024        # a file-history-snapshot record can be megabytes on
                            # its own — readline(size) keeps one line bounded
TITLE_CHARS = 90


def safe_name(segment: str):
    """One path segment → a flat filename, or None.

    The check runs *after* unquoting on a segment that was split off the raw
    path, so an encoded separator (%2F, %5C) is rejected here rather than
    silently becoming a directory step.
    """
    name = unquote(segment).strip()
    if not SAFE.match(name) or name in (".", "..") or name.startswith("."):
        return None
    return name


# ── Desk status ───────────────────────────────────────────────────────────
# Legacy Terminal snapshot and completion marker. The HTTP route merges this
# with Claude Chat observations, or selects independent Codex account metadata.
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def status() -> dict:
    data = _read_json(STATUS_FILE)
    if data is None:
        data = {}
    else:
        try:
            data["age"] = int(max(time.time() - os.path.getmtime(STATUS_FILE), 0))
        except OSError:
            pass
    # When the last turn ended, from the Stop hook (done-hook.sh). It rides
    # along here rather than on an endpoint of its own so the page's one poll
    # answers both questions.
    done = _read_json(DONE_FILE)
    if done and done.get("at"):
        data["done"] = done
    return data


# ── Sessions ──────────────────────────────────────────────────────────────
def _user_text(record: dict):
    """The words someone typed in this record, or None.

    Claude Code stores plenty of user-role records nobody typed: replayed
    slash commands arrive wrapped in <local-command-caveat>, tool results
    come back as the user turn. Both start with '<' or carry no text block,
    which is enough to tell them apart from a real first message.
    """
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text") or ""
                break
    else:
        return None
    text = " ".join(text.split())
    if not text or text.startswith("<"):
        return None
    return text


def title_of(path: str) -> str:
    """A name for a transcript: its summary if it has one, else the opener.

    Reads a bounded prefix of the file. One of these is 4.6 MB and grows,
    and the title always lives in the first few records.
    """
    first = None
    read = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            while read < TITLE_BUDGET:
                line = f.readline(MAX_LINE)
                if not line:
                    break
                read += len(line)
                # Cheap reject before parsing: most records are neither.
                if '"summary"' not in line and '"user"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue        # a line clipped at MAX_LINE lands here
                if not isinstance(record, dict):
                    continue
                if record.get("type") == "summary" and record.get("summary"):
                    return str(record["summary"])[:TITLE_CHARS]
                if first is None and record.get("type") == "user":
                    first = _user_text(record)
    except OSError:
        return ""
    return (first or "")[:TITLE_CHARS]


def sessions() -> list:
    try:
        found = [
            e for e in os.scandir(SESSION_DIR)
            if e.name.endswith(".jsonl") and e.is_file(follow_symlinks=False)
        ]
    except OSError:
        return []
    found.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    out = []
    for entry in found[:SESSION_LIMIT]:
        stat = entry.stat()
        out.append({
            "id": entry.name[:-len(".jsonl")],
            "title": title_of(entry.path),
            "mtime": int(stat.st_mtime),
            "size": stat.st_size,
        })
    return out


# ── The tmux pane ─────────────────────────────────────────────────────────
def _tmux(*args) -> tuple:
    """(ok, stdout). tmux missing or no server is a plain failure, not a raise."""
    try:
        done = subprocess.run(
            ["tmux", *args], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return done.returncode == 0, done.stdout.strip()


def pane_command(target: str = None):
    """Name of the program with the keyboard in the desk's pane, or None."""
    ok, name = _tmux(
        "display-message", "-p", "-t", target or TMUX_TARGET,
        "#{pane_current_command}"
    )
    return name if ok and name else None


def type_into_pane(line: str, target: str = None) -> tuple:
    """(code, message). Refuses while a program owns the pane."""
    target = target or TMUX_TARGET
    current = pane_command(target)
    if current is None:
        return 503, "no tmux pane"
    if current not in SHELLS:
        # The page turns this into "something is running — quit it first",
        # and offers the button that calls quit_pane below.
        return 409, "busy:" + current
    ok, _ = _tmux("send-keys", "-t", target, line, "Enter")
    return (200, "ok") if ok else (503, "send-keys failed")


def quit_pane(target: str = None) -> tuple:
    """Put the pane back at a shell prompt.

    Without this the sheet is a trap: "New session" starts Claude Code in the
    pane, and from then on every row in the sheet is refused until someone
    quits it by hand — which on a phone means typing into the terminal, the
    thing the sheet exists to avoid.

    Escape first, so the next line lands in an empty prompt box instead of
    being appended to a half-typed message or a running turn. Then `/exit`,
    which is what actually quits: Ctrl-C twice is the documented way out and
    was measured **not** to work through `send-keys` (the pane still reported
    `claude` afterwards), while Escape + `/exit` returned it to `bash` both at
    an idle prompt and mid-turn.
    """
    target = target or TMUX_TARGET
    current = pane_command(target)
    if current is None:
        return 503, "no tmux pane"
    if current in SHELLS:
        return 200, current
    _tmux("send-keys", "-t", target, "Escape")
    time.sleep(0.4)
    _tmux("send-keys", "-t", target, "/exit", "Enter")
    deadline = time.time() + QUIT_WAIT
    while time.time() < deadline:
        time.sleep(0.5)
        now = pane_command(target)
        if now is None or now in SHELLS:
            return 200, now or "gone"
    # Something that does not answer /exit — say so rather than pretending.
    return 409, "busy:" + (pane_command(target) or "?")


class Handler(BaseHTTPRequestHandler):
    server_version = "ai-deck-files/2"

    def _reply(self, code: int, body: str = ""):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _json(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _desk(self) -> str:
        """The tmux target this request may drive.

        nginx overwrites X-Desk-User with $remote_user on the way in
        (proxy_set_header wins over whatever the browser sent), and nginx is
        the only thing that can reach this port.
        """
        owner = self.headers.get("X-Desk-User") or ""
        if workspace_api.enabled():
            from coding_terminal import session_name
            ident = parse_qs(urlparse(self.path).query).get('workspace', [''])[0]
            return session_name(owner, ident)
        return target_for(owner)

    def _route(self):
        """('in'|'out', name or None) — None name means "the whole folder"."""
        raw = self.path.split("?", 1)[0]
        parts = raw.split("/")
        # ['', 'upload', <dir>, <name or ''>] and nothing deeper
        if len(parts) != 4 or parts[0] != "" or parts[1] != "upload":
            self._reply(404, "not here")
            return None, None
        folder = DIRS.get(unquote(parts[2]))
        if folder is None:
            self._reply(404, "no such folder")
            return None, None
        if parts[3] == "":
            return folder, None
        name = safe_name(parts[3])
        if not name:
            self._reply(400, "bad name")
            return None, None
        return folder, name

    def _provider(self):
        if workspace_api.enabled():
            if not self.headers.get('X-Desk-User'):
                self._reply(401, 'Authentication required')
                return None
            ident = parse_qs(urlparse(self.path).query).get('workspace', [''])[0]
            if ident:
                from workspaces import WorkspaceError
                try:
                    workspace_api.workspace(self)
                except WorkspaceError as exc:
                    self._reply(exc.status, exc.message)
                    return None
        provider = parse_qs(urlparse(self.path).query).get("provider", ["claude"])[0]
        if provider not in ("claude", "codex"):
            self._reply(400, "unknown provider")
            return None
        return provider

    def do_GET(self):
        provider = self._provider()
        if provider is None:
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/auth" and provider == "codex":
            self._json(agent_options.auth_status())
        elif path == "/api/status":
            force = parse_qs(urlparse(self.path).query).get("refresh") == ["1"]
            self._json(usage_status.codex_status(force) if provider == "codex"
                       else usage_status.claude_status(status(), force))
        elif path == "/api/sessions" and workspace_api.enabled():
            from workspaces import WorkspaceError
            try:
                item = workspace_api.workspace(self)
                import chat
                items = codex_backend.sessions(item['path']) if provider == 'codex' else chat.workspace_sessions(item['path'])
                self._json({'sessions': items, 'pane': pane_command(self._desk())})
            except WorkspaceError as exc:
                self._reply(exc.status, exc.message)
        elif path == "/api/sessions":
            # The pane's state ships with the list so the sheet can say up
            # front that resuming is not possible right now, rather than
            # letting every tap come back 409.
            self._json({"sessions": codex_backend.sessions(WORK_DIR) if provider == "codex" else sessions() if provider == "claude" else [], "pane": pane_command(self._desk())})
        else:
            self._reply(404, "not here")

    def do_POST(self):
        provider = self._provider()
        if provider is None:
            return
        path = self.path.split("?", 1)[0]
        workspace_path = None
        if workspace_api.enabled() and path in ("/api/new", "/api/resume"):
            from workspaces import WorkspaceError
            try:
                workspace_path = workspace_api.workspace(self)['path']
            except WorkspaceError as exc:
                self._reply(exc.status, exc.message)
                return
        if path == "/api/new":
            command = ('cd -- ' + shlex.quote(workspace_path) + ' && ' if workspace_path else '') + provider
            code, message = type_into_pane(command, self._desk())
        elif path == "/api/login" and provider == "codex":
            code, message = type_into_pane("codex login --device-auth", self._desk())
        elif path == "/api/quit":
            code, message = quit_pane(self._desk())
        elif path == "/api/resume":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 4096:
                    self.close_connection = True
                    self._reply(413 if length > 4096 else 400, "invalid body length")
                    return
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
                session_id = body.get("id", "")
            except ValueError:
                self._reply(400, "bad json")
                return
            # A uuid and nothing else: this string is about to be typed into
            # an interactive shell.
            if not isinstance(session_id, str) or not UUID.fullmatch(session_id):
                self._reply(400, "bad id")
                return
            if workspace_path:
                import chat
                exists = codex_backend.rollout(session_id, workspace_path) if provider == 'codex' else chat.session_exists(session_id, workspace_path)
                if not exists:
                    self._reply(404, 'Session not found in this workspace')
                    return
            prefix = 'cd -- ' + shlex.quote(workspace_path) + ' && ' if workspace_path else ''
            code, message = type_into_pane(
                prefix + ("codex resume " if provider == "codex" else "claude --resume ") + session_id, self._desk()
            )
        else:
            self._reply(404, "not here")
            return
        self._reply(code, message)

    def do_PUT(self):
        folder, name = self._route()
        if folder is None:
            return
        if name is None:
            self._reply(405, "name required")
            return
        if folder != DIRS["in"]:
            # out/ is Claude's output; uploading over it would only confuse.
            self._reply(403, "uploads go to in/")
            return
        path = os.path.join(folder, name)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0:
                raise ValueError
        except ValueError:
            self._reply(400, "bad content length")
            return
        tmp = None
        try:
            # Each upload owns its temp file, including simultaneous same-name uploads.
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".upload-", delete=False) as f:
                tmp = f.name
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        raise EOFError("incomplete upload")
                    f.write(chunk)
                    left -= len(chunk)
            os.chmod(tmp, 0o644)  # nginx serves previews using a separate uid.
            os.replace(tmp, path)   # atomic: never a half file under its real name
        except (OSError, EOFError) as e:
            try:
                if tmp is not None:
                    os.unlink(tmp)
            except OSError:
                pass
            self._reply(400 if isinstance(e, EOFError) else 500, str(e))
            return
        self._reply(201, "ok")

    def do_DELETE(self):
        folder, name = self._route()
        if folder is None:
            return
        if name is None:
            self._reply(200, str(self._clear(folder)))
            return
        try:
            os.unlink(os.path.join(folder, name))
        except FileNotFoundError:
            self._reply(404, "no such file")
            return
        except OSError as e:
            self._reply(500, str(e))
            return
        self._reply(204)

    @staticmethod
    def _clear(folder: str) -> int:
        """Unlink every plain file directly in folder. Returns how many.

        Subdirectories are left alone — that keeps Synology's @eaDir (and
        anything Claude organised into a folder) out of it. A .part file
        belonging to an upload still in flight is removed like any other,
        and that upload then fails on its rename; clearing mid-upload is
        assumed to be what was meant.
        """
        removed = 0
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return 0
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                continue
            try:
                os.unlink(entry.path)
                removed += 1
            except OSError:
                pass
        return removed

    def log_message(self, fmt, *args):  # one line per request, to the container log
        sys.stderr.write("[upload] %s %s\n" % (self.command, fmt % args))


if __name__ == "__main__":
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
