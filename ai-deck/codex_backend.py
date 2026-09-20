"""Codex CLI JSONL adapter and saved rollout reader (no API key proxy)."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading

UUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


def session_root():
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"


def records(path):
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        yield record
                except ValueError:
                    continue  # A live rollout can end in a partial line.
    except OSError:
        return


def rollout(session_id, cwd):
    if not UUID.fullmatch(session_id):
        return None
    for path in session_root().glob("**/*" + session_id + ".jsonl"):
        meta = next(records(path), {}).get("payload", {})
        if meta.get("id") == session_id and meta.get("cwd") == cwd:
            return path
    return None


def transcript(session_id, cwd):
    path = rollout(session_id, cwd)
    if path is None:
        return []
    items = []
    for record in records(path):
        payload = record.get("payload") or {}
        if record.get("type") == "event_msg":
            kind = payload.get("type")
            if kind in ("user_message", "agent_message") and payload.get("message"):
                items.append({"k": "you" if kind == "user_message" else "claude",
                              "text": payload["message"]})
    return items


def sessions(cwd, limit=50):
    found = []
    for path in session_root().glob("**/*.jsonl"):
        try:
            meta = next(records(path), {}).get("payload", {})
            session_id = meta.get("id", "")
            if meta.get("cwd") != cwd or not UUID.fullmatch(session_id):
                continue
            title = ""
            for record in records(path):
                payload = record.get("payload") or {}
                if record.get("type") == "event_msg" and payload.get("type") == "user_message":
                    title = str(payload.get("message", ""))[:160]
                    break
            stat = path.stat()
            found.append({"id": session_id, "title": title, "mtime": stat.st_mtime,
                          "size": stat.st_size, "provider": "codex"})
        except OSError:
            continue
    return sorted(found, key=lambda item: item["mtime"], reverse=True)[:limit]


class CodexMixin:
    """Use Agent's SSE replay ring; one exec child per turn resumes its thread."""

    def send(self, text, model=None, effort=None):
        with self.lock:
            if self.busy:
                return 409, "still working"
            self.model = self.model if model is None else model
            self.effort = self.effort if effort is None else effort
            args = ["codex", "exec", "--json", "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox"]
            if self.model:
                args += ["--model", self.model]
            if self.effort:
                args += ["-c", "model_reasoning_effort=" + json.dumps(self.effort)]
            if self.session_id:
                args += ["resume", self.session_id]
            args.append("-")
            errors = tempfile.TemporaryFile(mode="w+")
            try:
                self.proc = subprocess.Popen(args, cwd=self.cwd, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=errors,
                                             text=True, start_new_session=True)
                self.proc.stdin.write(text)
                self.proc.stdin.close()
            except (OSError, ValueError):
                if self.proc and self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.wait()
                errors.close()
                return 503, "Codex could not start. Check installation and sign in from Terminal."
            self.busy = True
            self._interrupted = False
            self.emit(t="busy", on=True)
            threading.Thread(target=self._read_codex, args=(self.proc, errors), daemon=True).start()
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
            # Kill descendants too; an uncooperative tool must not keep Stop stuck.
            threading.Thread(target=self._reap_codex, args=(self.proc,), daemon=True).start()
            return 200, "ok"

    @staticmethod
    def _reap_codex(proc):
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        # A child can ignore TERM even if the group leader has already exited,
        # keeping stdout open and the reader busy forever.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def reset(self, resume=""):
        with self.lock:
            if self.busy:
                return 409, "still working"
            if resume and rollout(resume, self.cwd) is None:
                return 404, "Codex session not found in this workspace"
            self.session_id = resume or None
            self.spent = 0.0
            self.partial = ""
            self.open_tools = []
            self.emit(t="reset", session_id=resume)
            self.emit(t="busy", on=False)
            return 200, "ok"

    def _read_codex(self, proc, errors):
        usage, failure, tools = {}, "", set()
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                if kind == "thread.started":
                    self.session_id = event.get("thread_id")
                elif kind in ("turn.failed", "error"):
                    error = event.get("error") or {}
                    failure = str(error.get("message") or event.get("message") or "Codex turn failed")
                elif kind == "turn.completed":
                    usage = event.get("usage") or {}
                elif kind in ("item.started", "item.completed"):
                    item = event.get("item") or {}
                    name = item.get("type", "")
                    if name == "agent_message" and kind == "item.completed":
                        self.emit(t="say_start")
                        self.emit(t="say", text=item.get("text", ""))
                        self.emit(t="say_end")
                    elif name in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                        item_id = item.get("id")
                        if item_id not in tools:
                            tools.add(item_id)
                            detail = str(item.get("command") or item.get("query") or item.get("tool") or "")[:90]
                            self.open_tools.append({"name": name, "detail": detail})
                            self.emit(t="tool", name=name, detail=detail)
                        if kind == "item.completed":
                            if self.open_tools:
                                self.open_tools.pop(0)
                            self.emit(t="tool_done", ok=item.get("status") != "failed" and item.get("exit_code", 0) in (0, None))
            code = proc.wait()
            if code and not failure:
                errors.seek(0)
                failure = errors.read()[-1500:] or "Codex exited before completing the turn"
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
                          context=usage.get("input_tokens", 0), out=usage.get("output_tokens", 0), ms=0)
                self.emit(t="busy", on=False)
