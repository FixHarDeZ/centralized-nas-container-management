"""MiMoCode `run --format json` adapter and read-only session store reader."""

import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import tempfile
import threading

# Typed into a shell by upload.py's resume, so tight: ses_ + base62.
SESSION_ID = re.compile(r"^ses_[A-Za-z0-9]{16,40}$")
CONFIG = Path(__file__).resolve().parent / "mimocode.jsonc"
# MiMoCode's own variants for a reasoning model on an openai-compatible
# provider (`mimo models --verbose`): each sets reasoningEffort. Default
# (no --variant) keeps the config's pinned `low`.
EFFORTS = ["low", "medium", "high"]


def models():
    """The model menu, read from the same mimocode.jsonc MiMoCode runs with."""
    try:
        # Comments in that file are whole `//` lines only.
        text = "\n".join(line for line in CONFIG.read_text().splitlines()
                         if not line.lstrip().startswith("//"))
        configured = json.loads(text)["provider"]["mimo"]["models"]
    except (OSError, ValueError, KeyError):
        configured = {}
    return [{"id": "", "label": "Default", "efforts": []}] + [
        {"id": name, "label": item.get("name") or name,
         "efforts": EFFORTS if item.get("reasoning") else []}
        for name, item in configured.items()]


def db_path():
    if os.environ.get("MIMOCODE_DB"):
        return Path(os.environ["MIMOCODE_DB"])
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "mimocode" / "mimocode.db"


def _query(sql, args=()):
    path = db_path()
    if not path.exists():
        return []
    try:
        # Read-only: MiMoCode owns this WAL database and may be writing now.
        with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True, timeout=2) as db:
            return db.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


# MiMoCode imports Claude Code transcripts into the same table; those are not
# resumable here, so only sessions without an anthropic message are listed.
_OWN = """s.parent_id IS NULL AND s.time_archived IS NULL AND s.directory = ?
  AND NOT EXISTS (SELECT 1 FROM message m WHERE m.session_id = s.id
                  AND json_extract(m.data, '$.model.providerID') = 'anthropic')"""


def tokens_since(since_ms):
    """Tokens MiMoCode logged since `since_ms`, from every chat and terminal session.

    `tokens.total` of each step already includes cache reads. Only mimo
    provider steps (imported Claude transcripts carry their own). Not seen:
    `ask`, other stacks sharing the key, and sessions deleted since.
    """
    rows = _query("""SELECT SUM(json_extract(p.data, '$.tokens.total')) FROM part p
                     JOIN message m ON m.id = p.message_id
                     WHERE p.time_created >= ? AND json_extract(p.data, '$.type') = 'step-finish'
                       AND json_extract(m.data, '$.providerID') = 'mimo'""", (since_ms,))
    return int(rows[0][0] or 0) if rows else 0


def session_exists(session_id, cwd):
    if not SESSION_ID.fullmatch(session_id or ""):
        return False
    return bool(_query("SELECT 1 FROM session s WHERE s.id = ? AND " + _OWN, (session_id, cwd)))


def sessions(cwd, limit=50):
    rows = _query("SELECT s.id, s.title, s.time_updated FROM session s WHERE " + _OWN
                  + " ORDER BY s.time_updated DESC LIMIT ?", (cwd, limit))
    return [{"id": sid, "title": (title or "").strip('"')[:160], "mtime": updated / 1000,
             "size": 0, "provider": "mimo"} for sid, title, updated in rows]


def transcript(session_id, cwd):
    if not session_exists(session_id, cwd):
        return []
    rows = _query("""SELECT json_extract(m.data, '$.role'), p.data FROM part p
                     JOIN message m ON m.id = p.message_id
                     WHERE p.session_id = ? AND m.agent_id = 'main'
                     ORDER BY m.time_created, p.id""", (session_id,))
    items = []
    for role, data in rows:
        try:
            part = json.loads(data)
        except ValueError:
            continue
        text = part.get("text") if part.get("type") == "text" else None
        if not text or part.get("synthetic") or text.lstrip().startswith("<"):
            continue
        items.append({"k": "you" if role == "user" else "claude", "text": text})
    return items


class MimoMixin:
    """Use Agent's SSE replay ring; one `mimo run` child per turn resumes its session."""

    def send(self, text, model=None, effort=None):
        with self.lock:
            if self.busy:
                return 409, "still working"
            self.model = self.model if model is None else model
            self.effort = self.effort if effort is None else effort
            args = ["mimo", "run", "--format", "json"]
            if self.model:
                args += ["-m", "mimo/" + self.model]
            if self.effort:
                args += ["--variant", self.effort]
            if self.session_id:
                args += ["-s", self.session_id]
            # `--` so a message starting with a dash stays the message.
            args += ["--", text]
            env = dict(os.environ, MIMOCODE_DANGEROUSLY_SKIP_PERMISSIONS="1",
                       CLAUDE_CODE_OAUTH_TOKEN="")
            errors = tempfile.TemporaryFile(mode="w+")
            try:
                # stdin closed: `run` appends a non-TTY stdin to the message.
                self.proc = subprocess.Popen(args, cwd=self.cwd, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=errors, env=env,
                                             text=True, start_new_session=True)
            except OSError:
                errors.close()
                return 503, "MiMoCode could not start. Check installation and MIMO_API_KEY."
            self.busy = True
            self._interrupted = False
            self.emit(t="busy", on=True)
            threading.Thread(target=self._read_mimo, args=(self.proc, errors), daemon=True).start()
            return 200, "ok"

    def interrupt(self):
        with self.lock:
            if not self.busy or not self.running():
                return 409, "nothing running"
            self._interrupted = True
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            threading.Thread(target=self._reap_mimo, args=(self.proc,), daemon=True).start()
            return 200, "ok"

    @staticmethod
    def _reap_mimo(proc):
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def reset(self, resume=""):
        with self.lock:
            if self.busy:
                return 409, "still working"
            # `-s` resumes any session regardless of cwd; the workspace check is ours.
            if resume and not session_exists(resume, self.cwd):
                return 404, "MiMoCode session not found in this workspace"
            self.session_id = resume or None
            self.spent = 0.0
            self.partial = ""
            self.open_tools = []
            self.emit(t="reset", session_id=resume)
            self.emit(t="busy", on=False)
            return 200, "ok"

    def _read_mimo(self, proc, errors):
        context, out, failure = 0, 0, ""
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("sessionID") and not self.session_id:
                    self.session_id = event["sessionID"]
                kind = event.get("type")
                part = event.get("part") or {}
                if kind == "text" and part.get("text"):
                    # Whole parts, not deltas.
                    self.emit(t="say_start")
                    self.emit(t="say", text=part["text"])
                    self.emit(t="say_end")
                elif kind == "tool_use":
                    state = part.get("state") or {}
                    given = state.get("input") or {}
                    detail = str(state.get("title") or given.get("command")
                                 or given.get("filePath") or given.get("pattern") or "")[:90]
                    self.emit(t="tool", name=str(part.get("tool") or "tool"), detail=detail)
                    exit_code = (state.get("metadata") or {}).get("exit", 0)
                    self.emit(t="tool_done", ok=state.get("status") != "error" and exit_code in (0, None))
                elif kind == "step_finish":
                    tokens = part.get("tokens") or {}
                    # Each step re-sends the conversation: last input is the context, outputs add up.
                    context = (tokens.get("input") or 0) + ((tokens.get("cache") or {}).get("read") or 0)
                    out += tokens.get("output") or 0
                elif kind == "error":
                    # Exit code stays 0 on a model error, so this event is the only signal.
                    error = event.get("error") or {}
                    failure = str((error.get("data") or {}).get("message") or error.get("name")
                                  or "MiMoCode turn failed")
            code = proc.wait()
            if code and not failure and not self._interrupted:
                errors.seek(0)
                failure = errors.read()[-1500:] or "MiMoCode exited before completing the turn"
        except (OSError, ValueError) as exc:
            failure = str(exc)
        finally:
            errors.close()
            proc.stdout.close()
            with self.lock:
                self.busy = False
                self.open_tools = []
                self.emit(t="turn", status="stopped" if self._interrupted else "error" if failure else "done",
                          reason=failure, text=failure, cost=None, total=None,
                          context=context, out=out, ms=0)
                self.emit(t="busy", on=False)
