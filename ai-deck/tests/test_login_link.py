"""Server-side copy of the sign-in link rules + the Telegram relay watcher.

Same cases as tests/claude_login_harness.html: the two copies of the rule
(ui/app.js and login_link.py) must not drift, which is exactly how the panel
went silent on 11-11 (/cai/) and 11-23 (?z-).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import login_link

FIXTURES = Path(__file__).parent / "fixtures"
LONG = ('https://claude.com/cai/oauth/authorize?code=true&client_id=fixture&response_type=code'
        '&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback'
        '&code_challenge=' + 'fixture' * 20 + '&code_challenge_method=S256&state=fixture%2Bstate')
SHORT = 'https://claude.ai/oauth/authorize?z-' + 'Fx_8-Qa9' * 5 + 'zE3'
CFG = ("http://n8n.test/webhook/desk-login", "secret", ["fixhardez"])


def test_accepts_every_known_link_shape():
    tmux = json.loads((FIXTURES / "claude_login_tmux.json").read_text())
    for url in (LONG, SHORT, tmux["url"]):
        assert login_link.is_login_url(url), url


def test_rejects_lookalikes():
    for url in (
        'https://example.com/oauth/authorize?state=bad',
        LONG.replace('claude.com/', 'claude.com.evil.example/'),
        LONG.replace('https://', 'https://someone@'),
        SHORT.replace('claude.ai/', 'claude.ai:8443/'),
        SHORT.replace('claude.ai/', 'claude.ai.evil.example/'),
        SHORT.replace('https://', 'http://'),
        'https://claude.ai/oauth/authorize?z-',
        'https://claude.ai/oauth/authorize?z-abc&x=1',
        'https://claude.ai/oauth/authorize?z-' + 'a' * 20 + '&x=1',
        'https://claude.ai/evil/path/oauth/authorize?z-' + 'a' * 20,
    ):
        assert not login_link.is_login_url(url), url


def test_finds_link_in_real_pane_text():
    pane = ("desk /work > claude auth login\nOpening browser to sign in…\n"
            "If the browser didn't open, visit:\n" + SHORT + "\nPaste code here if prompted > ")
    assert login_link.find_login_urls(pane) == [SHORT]


def test_config_off_unless_all_three_set():
    assert login_link.config({}) is None
    assert login_link.config({"DESK_LOGIN_WEBHOOK": "x", "DESK_LOGIN_TOKEN": "t"}) is None
    assert login_link.config({"DESK_LOGIN_WEBHOOK": "x", "DESK_LOGIN_NOTIFY": "a"}) is None
    assert login_link.config({"DESK_LOGIN_WEBHOOK": "x", "DESK_LOGIN_TOKEN": "t",
                              "DESK_LOGIN_NOTIFY": " Fixhardez , "}) == ("x", "t", ["fixhardez"])


def test_watch_skips_old_link_and_sends_new_one_once():
    old = SHORT.replace('Fx_8', 'Old0')
    screens = iter([old, old + "\n" + SHORT, old + "\n" + SHORT])
    sent = []
    url = login_link.watch("fixhardez:0.0", "fixhardez", {old}, CFG,
                           screen=lambda t: next(screens),
                           sender=lambda *a: sent.append(a) or True, seconds=5, poll=0)
    assert url == SHORT
    assert sent == [(CFG[0], CFG[1], SHORT, "fixhardez")]


def test_watch_gives_up_quietly():
    sent = []
    assert login_link.watch("t", "d", set(), CFG, screen=lambda t: "nothing",
                            sender=lambda *a: sent.append(a), seconds=0.05, poll=0.01) == ""
    assert sent == []


def test_start_only_for_listed_desks():
    assert not login_link.start("pookzii:0.0", "pookzii", {"fixhardez:0.0"}, set(), CFG)
    assert not login_link.start("fixhardez:0.0", "fixhardez", {"fixhardez:0.0"}, set(), None)


def test_send_posts_json_with_token(monkeypatch):
    seen = {}

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), token=req.get_header("X-desk-token"))
        return Resp()

    monkeypatch.setattr(login_link.urllib.request, "urlopen", fake_urlopen)
    assert login_link.send(CFG[0], "secret", SHORT, "fixhardez")
    assert seen == {"url": CFG[0], "body": {"url": SHORT, "desk": "fixhardez"}, "token": "secret"}


def test_send_failure_is_false_not_raise(monkeypatch):
    def boom(*a, **k):
        raise OSError("refused")
    monkeypatch.setattr(login_link.urllib.request, "urlopen", boom)
    assert login_link.send(CFG[0], "secret", SHORT, "fixhardez") is False


def test_upload_login_starts_watcher_for_owner_desk(monkeypatch):
    """/api/login wires the watcher with the right desk + pre-existing links."""
    import upload
    monkeypatch.setattr(upload, "DESKS", upload.roster("fixhardez:7681,Pookzii:7684"))
    calls = []
    monkeypatch.setattr(upload.login_link, "config", lambda: CFG)
    monkeypatch.setattr(upload.login_link, "_screen", lambda t: "old " + SHORT)
    monkeypatch.setattr(upload.login_link, "start", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(upload, "type_into_pane", lambda line, target: (200, "ok"))
    # Drive the handler branch without a socket.
    h = upload.Handler.__new__(upload.Handler)
    h.path = "/api/login"
    h.headers = {"X-Desk-User": "fixhardez"}
    replies = []
    h._reply = lambda code, msg="": replies.append((code, msg))
    h._provider = lambda: "claude"
    h.do_POST()
    assert replies == [(200, "ok")]
    target, desk, wanted, before, cfg = calls[0]
    assert (target, desk, before, cfg) == ("fixhardez:0.0", "fixhardez", {SHORT}, CFG)
    assert wanted == {"fixhardez:0.0"}
