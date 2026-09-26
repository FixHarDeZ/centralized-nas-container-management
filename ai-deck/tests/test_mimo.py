"""Exercise MiMoCode's `run --format json` contract without an API key or paid turn."""
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

import pytest

import agent_options
import chat
import mimo_backend

SID = "ses_ffe5f24485b9fffe7aLN12JZOJ"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fake_mimo(tmp_path, monkeypatch):
    binary = tmp_path / "mimo"
    # Event shapes captured from mimo 0.1.15 on the NAS (2026-09-26).
    binary.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
Path("received.json").write_text(json.dumps({"args": args, "stdin_tty": sys.stdin.isatty(),
    "stdin": sys.stdin.read() if not sys.stdin.closed else "",
    "skip": os.environ.get("MIMOCODE_DANGEROUSLY_SKIP_PERMISSIONS"),
    "oauth": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")}))
prompt = args[-1]
sid = "ses_ffe5f24485b9fffe7aLN12JZOJ"
def emit(kind, **part):
    print(json.dumps({"type": kind, "sessionID": sid, "part": part}), flush=True)
if prompt == "fail":
    print(json.dumps({"type": "error", "sessionID": sid,
        "error": {"name": "UnknownError", "data": {"message": "Model not found: mimo/nope."}}}), flush=True)
    sys.exit(0)
emit("step_start", type="step-start")
emit("tool_use", type="tool", tool="bash", state={"status": "completed", "input": {"command": "echo hi"},
     "metadata": {"exit": 0}, "title": "Echo hi"})
if prompt == "wait":
    time.sleep(60)
emit("step_finish", type="step-finish", tokens={"input": 29118, "output": 33, "cache": {"read": 0}})
emit("text", type="text", text="ok")
emit("step_finish", type="step-finish", tokens={"input": 125, "output": 3, "cache": {"read": 29056}})
''')
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")
    monkeypatch.setenv("MIMOCODE_DB", str(tmp_path / "none.db"))
    return tmp_path


def events_until(channel, kind):
    events = []
    while True:
        event = channel.get(timeout=5)
        events.append(event)
        if event["t"] == kind:
            return events


def test_turn_resume_and_literal_prompt(fake_mimo):
    agent = chat.MimoAgent(cwd=str(fake_mimo))
    channel = agent.subscribe()
    prompt = "--help สวัสดี $(touch NEVER)"
    assert agent.send(prompt, model="mimo-v2.5")[0] == 200
    events = events_until(channel, "turn")
    assert [e["text"] for e in events if e["t"] == "say"] == ["ok"]
    assert [e["t"] for e in events if e["t"].startswith("tool")] == ["tool", "tool_done"]
    turn = events[-1]
    assert turn["status"] == "done" and turn["cost"] is None
    assert (turn["context"], turn["out"]) == (125 + 29056, 36)
    assert agent.session_id == SID
    received = json.loads((fake_mimo / "received.json").read_text())
    assert received["args"][-2:] == ["--", prompt]
    assert received["args"][received["args"].index("-m") + 1] == "mimo/mimo-v2.5"
    assert received["stdin"] == "" and not received["stdin_tty"]
    assert received["skip"] == "1" and received["oauth"] == ""
    assert not (fake_mimo / "NEVER").exists()
    agent.send("again")
    events_until(channel, "turn")
    args = json.loads((fake_mimo / "received.json").read_text())["args"]
    assert args[args.index("-s") + 1] == SID


def test_error_event_with_exit_zero_is_failure(fake_mimo):
    agent = chat.MimoAgent(cwd=str(fake_mimo))
    channel = agent.subscribe()
    agent.send("fail")
    turn = events_until(channel, "turn")[-1]
    assert turn["status"] == "error"
    assert "Model not found" in turn["text"]
    assert not agent.busy


def test_stop(fake_mimo):
    agent = chat.MimoAgent(cwd=str(fake_mimo))
    channel = agent.subscribe()
    assert agent.send("wait")[0] == 200
    events_until(channel, "tool_done")
    assert agent.send("second")[0] == 409
    assert agent.interrupt()[0] == 200
    assert events_until(channel, "turn")[-1]["status"] == "stopped"
    assert not agent.busy


def test_missing_mimo_is_recoverable(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    agent = chat.MimoAgent(cwd=str(tmp_path))
    assert agent.send("hello")[0] == 503
    assert not agent.busy


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "mimocode.db"
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE session (id text, parent_id text, directory text, title text,
        time_updated integer, time_archived integer);
      CREATE TABLE message (id text, session_id text, agent_id text, time_created integer, data text);
      CREATE TABLE part (id text, message_id text, session_id text, data text);
    """)
    def add(sid, cwd, title, provider="mimo", parent=None, updated=1):
        db.execute("INSERT INTO session VALUES (?,?,?,?,?,NULL)", (sid, parent, cwd, title, updated))
        for n, (role, text) in enumerate([("user", "<local-command-caveat>x"), ("user", "hello"), ("assistant", "hi there")]):
            mid = sid + "m" + str(n)
            db.execute("INSERT INTO message VALUES (?,?,?,?,?)", (mid, sid, "main", n,
                       json.dumps({"role": role, "model": {"providerID": provider}})))
            db.execute("INSERT INTO part VALUES (?,?,?,?)", (mid + "p", mid, sid, json.dumps({"type": "text", "text": text})))
    add(SID, "/work", '"first"', updated=2)
    add("ses_AAAAAAAAAAAAAAAAAAAAAAAAAA", "/other", "elsewhere")
    add("ses_BBBBBBBBBBBBBBBBBBBBBBBBBB", "/work", "imported claude", provider="anthropic")
    add("ses_CCCCCCCCCCCCCCCCCCCCCCCCCC", "/work", "subagent", parent=SID)
    db.commit()
    db.close()
    monkeypatch.setenv("MIMOCODE_DB", str(path))
    return path


def test_sessions_filter_workspace_imports_and_subagents(store):
    assert [s["id"] for s in mimo_backend.sessions("/work")] == [SID]
    assert mimo_backend.sessions("/work")[0]["title"] == "first"
    assert mimo_backend.session_exists(SID, "/work")
    assert not mimo_backend.session_exists(SID, "/other")
    assert not mimo_backend.session_exists("ses_BBBBBBBBBBBBBBBBBBBBBBBBBB", "/work")


def test_transcript_skips_command_noise(store):
    assert mimo_backend.transcript(SID, "/work") == [
        {"k": "you", "text": "hello"}, {"k": "claude", "text": "hi there"}]
    assert mimo_backend.transcript(SID, "/other") == []


def test_resume_is_workspace_scoped(store, tmp_path):
    agent = chat.MimoAgent(cwd="/other")
    assert agent.reset(resume=SID)[0] == 404
    assert chat.MimoAgent(cwd="/work").reset(resume=SID)[0] == 200


def test_session_id_rule_is_shell_safe():
    assert mimo_backend.SESSION_ID.fullmatch(SID)
    for bad in ["ses_abc; rm -rf /", "ses_short", SID + "\n", "0199a213-81c0-7800-8aa1-bbab2a035a53"]:
        assert not mimo_backend.SESSION_ID.fullmatch(bad)


def test_models_come_from_mimocode_config():
    ids = [m["id"] for m in mimo_backend.models()]
    assert ids[0] == "" and {"mimo-v2.5-pro", "mimo-v2.6-pro", "mimo-v2.6-flash"} <= set(ids)
    assert all(m["efforts"] == ["low", "medium", "high"] for m in mimo_backend.models()[1:])
    assert agent_options.validate("mimo", "mimo-v2.6-pro", "high")
    assert agent_options.validate("mimo", "mimo-v2.5-pro", "")
    assert not agent_options.validate("mimo", "mimo-v2.5-pro", "max")
    assert not agent_options.validate("mimo", "gpt-5", "")


def test_unreadable_config_still_offers_default(monkeypatch, tmp_path):
    monkeypatch.setattr(mimo_backend, "CONFIG", tmp_path / "missing.jsonc")
    assert mimo_backend.models() == [{"id": "", "label": "Default", "efforts": []}]


def test_effort_becomes_variant(fake_mimo):
    agent = chat.MimoAgent(cwd=str(fake_mimo))
    channel = agent.subscribe()
    agent.send("hi", model="mimo-v2.6-pro", effort="high")
    events_until(channel, "turn")
    args = json.loads((fake_mimo / "received.json").read_text())["args"]
    assert args[args.index("--variant") + 1] == "high"
    agent.send("hi", model="", effort="")
    events_until(channel, "turn")
    assert "--variant" not in json.loads((fake_mimo / "received.json").read_text())["args"]
