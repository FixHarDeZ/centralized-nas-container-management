"""Exercise Codex's public JSONL contract without an account or paid turn."""
import http.client
import json
import os
import sys
import threading

import pytest

import chat
import codex_backend
import upload

SID = "0199a213-81c0-7800-8aa1-bbab2a035a53"


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    binary = tmp_path / "codex"
    binary.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys, time
from pathlib import Path
prompt = sys.stdin.read()
Path("received.json").write_text(json.dumps({"args":sys.argv[1:],"prompt":prompt}))
def emit(event):
    print(json.dumps(event), flush=True)
if prompt == "fail":
    emit({"type":"turn.failed","error":{"message":"Please sign in to Codex"}})
    sys.exit(1)
if prompt == "waitchild":
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"])
    time.sleep(0.2)
emit({"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a53"})
emit({"type":"item.started","item":{"id":"tool1","type":"command_execution","command":"echo hello"}})
if prompt in ("wait", "waitchild"):
    time.sleep(60)
emit({"type":"item.completed","item":{"id":"tool1","type":"command_execution","exit_code":0}})
emit({"type":"item.completed","item":{"id":"message1","type":"agent_message","text":"Hello from Codex"}})
emit({"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":5}})
''')
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    return tmp_path


def events_until(channel, kind):
    events = []
    while True:
        event = channel.get(timeout=5)
        events.append(event)
        if event["t"] == kind:
            return events


def test_codex_turn_resume_and_literal_prompt(fake_codex):
    agent = chat.CodexAgent(cwd=str(fake_codex))
    channel = agent.subscribe()
    prompt = 'Thai สวัสดี; $(touch NEVER) --help'
    assert agent.send(prompt)[0] == 200
    events = events_until(channel, "turn")
    assert [e["text"] for e in events if e["t"] == "say"] == ["Hello from Codex"], events
    assert events[-1]["status"] == "done"
    assert events[-1]["cost"] is None  # Tokens are not invented dollar costs.
    assert agent.session_id == SID
    assert not agent.busy
    received = json.loads((fake_codex / "received.json").read_text())
    assert received["prompt"] == prompt
    assert received["args"][-1] == "-"
    assert not (fake_codex / "NEVER").exists()
    assert agent.send("follow up")[0] == 200
    events_until(channel, "turn")
    args = json.loads((fake_codex / "received.json").read_text())["args"]
    assert args[-3:] == ["resume", SID, "-"]


@pytest.mark.parametrize("prompt", ["wait", "waitchild"])
def test_codex_stop_and_busy_guard(fake_codex, prompt):
    agent = chat.CodexAgent(cwd=str(fake_codex))
    channel = agent.subscribe()
    try:
        assert agent.send(prompt)[0] == 200
        events_until(channel, "tool")
        assert agent.send("second")[0] == 409
        assert agent.reset()[0] == 409
        assert agent.interrupt()[0] == 200
        assert events_until(channel, "turn")[-1]["status"] == "stopped"
        assert not agent.busy
        assert agent.proc.poll() is not None
        assert agent.session_id == SID
    finally:
        if agent.running():
            agent.interrupt()


def test_codex_failure_explains_auth(fake_codex):
    agent = chat.CodexAgent(cwd=str(fake_codex))
    channel = agent.subscribe()
    agent.send("fail")
    result = events_until(channel, "turn")[-1]
    assert result["status"] == "error"
    assert "sign in" in result["text"]
    assert not agent.busy


def test_missing_codex_is_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    agent = chat.CodexAgent(cwd=str(tmp_path))
    assert agent.send("hello")[0] == 503
    assert not agent.busy


def test_rollout_history_filters_workspace_and_ignores_partial_line(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    root = tmp_path / "sessions" / "2026" / "09" / "18"
    root.mkdir(parents=True)
    path = root / ("rollout-test-" + SID + ".jsonl")
    events = [
        {"type": "session_meta", "payload": {"id": SID, "cwd": "/work"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "สรุปเอกสาร"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "เรียบร้อย"}},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + '\n{"partial":')
    assert codex_backend.sessions("/work")[0]["title"] == "สรุปเอกสาร"
    assert codex_backend.sessions("/other") == []
    assert codex_backend.transcript(SID, "/work") == [
        {"k": "you", "text": "สรุปเอกสาร"}, {"k": "claude", "text": "เรียบร้อย"}]
    assert codex_backend.transcript("../../escape", "/work") == []
    assert codex_backend.transcript(SID, "/other") == []
    assert chat.CodexAgent(cwd="/work").reset(SID)[0] == 200
    assert chat.CodexAgent(cwd="/other").reset(SID)[0] == 404


def test_chat_agents_are_separate_per_authenticated_user_and_provider(monkeypatch):
    monkeypatch.setattr(chat, "AGENTS", {})
    alice = chat.agent_for("alice", "claude")
    bob = chat.agent_for("bob", "claude")
    codex = chat.agent_for("alice", "codex")
    assert alice is chat.agent_for("alice", "claude")
    assert len({id(alice), id(bob), id(codex)}) == 3
    alice.busy = True
    assert not bob.busy and not codex.busy


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(chat, "AGENTS", {})
    servers = []

    def request(handler, method, path, body=None, user="alice"):
        server = chat.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        connection.request(method, path, json.dumps(body) if body is not None else None,
                           {"X-Desk-User": user})
        response = connection.getresponse()
        code, data = response.status, response.read().decode()
        connection.close()
        return code, data

    yield request
    for server in servers:
        server.shutdown()
        server.server_close()


def test_http_routes_provider_and_login_without_shell_injection(api, monkeypatch):
    calls = []
    monkeypatch.setattr(upload, "type_into_pane", lambda line, target: (calls.append(line) or 200, "ok"))
    assert api(upload.Handler, "POST", "/api/new?provider=codex")[0] == 200
    assert api(upload.Handler, "POST", "/api/login?provider=codex")[0] == 200
    assert calls == ["codex", "codex login --device-auth"]
    assert api(upload.Handler, "POST", "/api/new?provider=codex%3Brm")[0] == 400
    assert len(calls) == 2


def test_http_chat_state_uses_selected_user_and_provider(api):
    chat.agent_for("alice", "codex").session_id = SID
    code, body = api(chat.Handler, "GET", "/chat/state?provider=codex")
    assert code == 200 and json.loads(body)["session_id"] == SID
    _, body = api(chat.Handler, "GET", "/chat/state?provider=codex", user="bob")
    assert json.loads(body)["session_id"] == ""
    _, body = api(chat.Handler, "GET", "/chat/state?provider=claude")
    assert json.loads(body)["session_id"] == ""
    assert api(chat.Handler, "GET", "/chat/state?provider=unknown")[0] == 400


@pytest.mark.parametrize("body", [[], "text", 12, {"text": ["hello"]}, {"text": ""}])
def test_chat_rejects_non_message_payloads(api, body):
    assert api(chat.Handler, "POST", "/chat/send?provider=codex", body)[0] == 400


@pytest.mark.parametrize("body", [[], {"id": [SID]}, {"id": SID + "\n"}, {"id": "../../escape"}])
def test_terminal_resume_rejects_malformed_payloads(api, body):
    assert api(upload.Handler, "POST", "/api/resume?provider=codex", body)[0] == 400
