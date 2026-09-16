"""The desk half of upload.py: session titles, status file, pane guard.

The file half (PUT/DELETE path rules) is exercised by running the server
directly — see the note in upload.py.
"""
import json
import os
import time

import pytest

import upload


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    d = tmp_path / "projects" / "-work"
    d.mkdir(parents=True)
    monkeypatch.setattr(upload, "SESSION_DIR", str(d))
    return d


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


# ── Titles ────────────────────────────────────────────────────────────────
def test_title_is_the_first_thing_someone_typed(sessions_dir):
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [
        {"type": "mode", "mode": "normal"},
        {"type": "permission-mode", "permissionMode": "bypassPermissions"},
        user("ทำ slide สรุปยอดขาย Q3"),
        user("อีกอัน"),
    ])
    assert upload.title_of(str(f)) == "ทำ slide สรุปยอดขาย Q3"


def test_title_reads_content_blocks_too(sessions_dir):
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "(empty)"},
            {"type": "text", "text": "list the files in /work/in"},
        ]}},
    ])
    assert upload.title_of(str(f)) == "list the files in /work/in"


def test_a_summary_wins_over_the_opener(sessions_dir):
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [
        user("hi"),
        {"type": "summary", "summary": "Q3 deck from the sales workbook"},
    ])
    assert upload.title_of(str(f)) == "Q3 deck from the sales workbook"


def test_bookkeeping_turns_are_not_titles(sessions_dir):
    """Replayed slash commands and tool results arrive as user records."""
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [
        user("<local-command-caveat>Caveat: The messages below…</local-command-caveat>"),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "(empty)"},
        ]}},
        user("the real question"),
    ])
    assert upload.title_of(str(f)) == "the real question"


def test_a_session_with_nothing_typed_has_no_title(sessions_dir):
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [{"type": "mode", "mode": "normal"}])
    assert upload.title_of(str(f)) == ""


def test_newlines_do_not_reach_the_row(sessions_dir):
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [user("first line\n\nsecond   line")])
    assert upload.title_of(str(f)) == "first line second line"


def test_title_is_clipped(sessions_dir):
    f = sessions_dir / "a.jsonl"
    write_jsonl(f, [user("x" * 500)])
    assert len(upload.title_of(str(f))) == upload.TITLE_CHARS


def test_a_huge_record_does_not_get_read_whole(sessions_dir, monkeypatch):
    """One file-history-snapshot line can be megabytes; the budget is bytes.

    The giant record comes first, so a reader without a cap would pull all of
    it into memory before ever reaching the message.
    """
    f = sessions_dir / "big.jsonl"
    huge = json.dumps({"type": "file-history-snapshot", "blob": "z" * 3_000_000})
    f.write_text(huge + "\n" + json.dumps(user("after the wall")) + "\n", encoding="utf-8")
    monkeypatch.setattr(upload, "TITLE_BUDGET", 64 * 1024)
    assert upload.title_of(str(f)) == ""


# ── Listing ───────────────────────────────────────────────────────────────
def test_sessions_are_newest_first_and_capped(sessions_dir, monkeypatch):
    monkeypatch.setattr(upload, "SESSION_LIMIT", 2)
    for i, name in enumerate(["old", "mid", "new"]):
        f = sessions_dir / (name + ".jsonl")
        write_jsonl(f, [user(name)])
        os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
    ids = [s["id"] for s in upload.sessions()]
    assert ids == ["new", "mid"]


def test_non_transcripts_are_ignored(sessions_dir):
    (sessions_dir / "memory").mkdir()
    (sessions_dir / "notes.txt").write_text("x", encoding="utf-8")
    write_jsonl(sessions_dir / "a.jsonl", [user("hi")])
    assert [s["id"] for s in upload.sessions()] == ["a"]


def test_a_missing_project_dir_is_an_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(upload, "SESSION_DIR", str(tmp_path / "nope"))
    assert upload.sessions() == []


# ── Status ────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def no_stray_desk_files(tmp_path, monkeypatch):
    """Point both files somewhere empty, so a real ~/.claude cannot leak in."""
    monkeypatch.setattr(upload, "STATUS_FILE", str(tmp_path / "absent-status.json"))
    monkeypatch.setattr(upload, "DONE_FILE", str(tmp_path / "absent-done.json"))


def test_status_reports_how_old_the_reading_is(tmp_path, monkeypatch):
    f = tmp_path / "desk-status.json"
    f.write_text(json.dumps({"five_hour": {"pct": 39}}), encoding="utf-8")
    os.utime(f, (time.time() - 3600, time.time() - 3600))
    monkeypatch.setattr(upload, "STATUS_FILE", str(f))
    got = upload.status()
    assert got["five_hour"]["pct"] == 39
    assert 3590 <= got["age"] <= 3610


def test_status_survives_a_half_written_file(tmp_path, monkeypatch):
    f = tmp_path / "desk-status.json"
    f.write_text('{"five_hour": ', encoding="utf-8")
    monkeypatch.setattr(upload, "STATUS_FILE", str(f))
    assert upload.status() == {}


def test_status_with_no_file_is_empty():
    assert upload.status() == {}


def test_the_finished_mark_rides_along_with_the_status(tmp_path, monkeypatch):
    done = tmp_path / "desk-done.json"
    done.write_text(json.dumps({"at": 1789534200, "session_id": "abc"}), encoding="utf-8")
    monkeypatch.setattr(upload, "DONE_FILE", str(done))
    assert upload.status()["done"]["at"] == 1789534200


def test_the_finished_mark_survives_no_status_file(tmp_path, monkeypatch):
    """The chip and the notification fail independently of each other."""
    done = tmp_path / "desk-done.json"
    done.write_text(json.dumps({"at": 5, "session_id": ""}), encoding="utf-8")
    monkeypatch.setattr(upload, "DONE_FILE", str(done))
    got = upload.status()
    assert got == {"done": {"at": 5, "session_id": ""}}


def test_a_half_written_finished_mark_is_dropped(tmp_path, monkeypatch):
    done = tmp_path / "desk-done.json"
    done.write_text('{"at":', encoding="utf-8")
    monkeypatch.setattr(upload, "DONE_FILE", str(done))
    assert "done" not in upload.status()


# ── The pane guard ────────────────────────────────────────────────────────
def test_resume_is_refused_while_a_program_holds_the_pane(monkeypatch):
    """Otherwise the command is typed into Claude Code's prompt as a message."""
    monkeypatch.setattr(upload, "pane_command", lambda: "node")
    sent = []
    monkeypatch.setattr(upload, "_tmux", lambda *a: (sent.append(a), (True, ""))[1])
    code, message = upload.type_into_pane("claude --resume x")
    assert code == 409
    assert message == "busy:node"
    assert sent == []


def test_resume_types_into_a_free_shell(monkeypatch):
    monkeypatch.setattr(upload, "pane_command", lambda: "bash")
    sent = []
    monkeypatch.setattr(upload, "_tmux", lambda *a: (sent.append(a), (True, ""))[1])
    code, _ = upload.type_into_pane("claude --resume x")
    assert code == 200
    assert sent == [("send-keys", "-t", upload.TMUX_TARGET, "claude --resume x", "Enter")]


def test_no_tmux_server_is_not_a_crash(monkeypatch):
    monkeypatch.setattr(upload, "pane_command", lambda: None)
    code, _ = upload.type_into_pane("claude")
    assert code == 503


# ── Quitting the pane ─────────────────────────────────────────────────────
# "New session" leaves Claude Code in the pane, so without this the sheet
# refuses every later visit and the only fix is typing in the terminal.
def test_quitting_sends_escape_then_exit(monkeypatch):
    """Ctrl-C twice is the documented way out and measured not to work here."""
    sent = []
    seen = iter(["claude", "claude", "bash"])
    monkeypatch.setattr(upload, "pane_command", lambda: next(seen))
    monkeypatch.setattr(upload, "_tmux", lambda *a: (sent.append(a), (True, ""))[1])
    monkeypatch.setattr(upload.time, "sleep", lambda _s: None)
    code, _ = upload.quit_pane()
    assert code == 200
    assert sent == [
        # Escape first, so /exit lands in an empty prompt box rather than
        # being appended to a half-typed message or a running turn.
        ("send-keys", "-t", upload.TMUX_TARGET, "Escape"),
        ("send-keys", "-t", upload.TMUX_TARGET, "/exit", "Enter"),
    ]


def test_quitting_an_already_free_pane_types_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(upload, "pane_command", lambda: "bash")
    monkeypatch.setattr(upload, "_tmux", lambda *a: (sent.append(a), (True, ""))[1])
    assert upload.quit_pane()[0] == 200
    assert sent == []


def test_a_pane_that_ignores_exit_is_reported_not_assumed(monkeypatch):
    monkeypatch.setattr(upload, "pane_command", lambda: "vim")
    monkeypatch.setattr(upload, "_tmux", lambda *a: (True, ""))
    monkeypatch.setattr(upload.time, "sleep", lambda _s: None)
    code, message = upload.quit_pane()
    assert code == 409
    assert message == "busy:vim"


def test_quitting_with_no_tmux_server_is_not_a_crash(monkeypatch):
    monkeypatch.setattr(upload, "pane_command", lambda: None)
    assert upload.quit_pane()[0] == 503


@pytest.mark.parametrize("bad", [
    "", "not-a-uuid", "../../etc/passwd",
    "3bb7d4ca-216a-4893-a150-b2b9aea26b72; rm -rf /",
    "3bb7d4ca216a4893a150b2b9aea26b72",
])
def test_only_a_uuid_can_reach_the_shell(bad):
    """This string is typed into an interactive shell, so the pattern is the wall."""
    assert not upload.UUID.match(bad)


def test_a_real_session_id_passes():
    assert upload.UUID.match("3bb7d4ca-216a-4893-a150-b2b9aea26b72")
