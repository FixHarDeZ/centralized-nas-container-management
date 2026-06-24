import json

import reminder_translate as rt


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def _ok_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def test_parses_json_object(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    good = json.dumps({"my": "a", "en": "b", "lo": "c", "km": "d"})
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp(_ok_payload(good)))
    out = rt.translate_reminder("ล้างห้องน้ำ")
    assert out == {"my": "a", "en": "b", "lo": "c", "km": "d"}


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    assert rt.translate_reminder("x") is None


def test_empty_content_returns_none(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp(_ok_payload("")))
    assert rt.translate_reminder("x") is None


def test_bad_json_returns_none(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp(_ok_payload("not json")))
    assert rt.translate_reminder("x") is None


def test_http_error_returns_none(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tok")
    monkeypatch.setattr(rt, "http_post", lambda *a, **k: _Resp({}, status=500))
    assert rt.translate_reminder("x") is None
