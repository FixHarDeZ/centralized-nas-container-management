import httpx
import pytest

import app.wallhaven as wallhaven


class _FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


def test_purpose_presets_has_fixed_keys():
    assert set(wallhaven.PURPOSE_PRESETS) == {"mobile", "pc"}
    assert wallhaven.PURPOSE_PRESETS["mobile"]["atleast"] == "1080x1920"
    assert wallhaven.PURPOSE_PRESETS["pc"]["atleast"] == "2560x1440"


def test_search_builds_expected_params(mocker):
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(json_data={"data": [{"id": "abc123", "path": "https://x/abc123.jpg", "file_type": "image/jpeg"}]})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)

    results = wallhaven.search(["IU"], "mobile", "toplist", page=1)

    assert captured["url"] == wallhaven.BASE_URL
    p = captured["params"]
    assert p["categories"] == "111"
    assert p["purity"] == "100"
    assert p["ratios"] == "9x16,9x19.5,9x20"
    assert p["atleast"] == "1080x1920"
    assert p["sorting"] == "toplist"
    assert p["page"] == 1
    assert p["q"] == "IU"
    assert results == [{"id": "abc123", "path": "https://x/abc123.jpg", "file_type": "image/jpeg"}]


def test_search_issues_one_request_per_alias_and_merges_by_id(mocker):
    calls = []

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        calls.append(params["q"])
        if params["q"] == '"Lee Ji-eun"':
            return _FakeResponse(json_data={"data": [{"id": "abc123", "path": "https://x/abc123.jpg"}]})
        if params["q"] == '"IU alt"':
            return _FakeResponse(json_data={"data": [{"id": "def456", "path": "https://x/def456.jpg"}]})
        return _FakeResponse(json_data={"data": [{"id": "abc123", "path": "https://x/abc123.jpg"}]})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)

    results = wallhaven.search(["IU", "Lee Ji-eun", "IU alt"], "mobile", "date_added")

    assert calls == ["IU", '"Lee Ji-eun"', '"IU alt"']
    assert {r["id"] for r in results} == {"abc123", "def456"}
    assert len(results) == 2


def test_search_quotes_multiword_terms(mocker):
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["q"] = params["q"]
        return _FakeResponse(json_data={"data": []})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)
    wallhaven.search(["Wuthering Waves"], "mobile", "toplist")
    assert captured["q"] == '"Wuthering Waves"'


def test_search_omits_apikey_when_not_set(mocker, monkeypatch):
    monkeypatch.delenv("WALLHAVEN_API_KEY", raising=False)
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["params"] = params
        return _FakeResponse(json_data={"data": []})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)
    wallhaven.search(["IU"], "mobile", "date_added")
    assert "apikey" not in captured["params"]


def test_search_includes_apikey_when_set(mocker, monkeypatch):
    monkeypatch.setenv("WALLHAVEN_API_KEY", "test-key")
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["params"] = params
        return _FakeResponse(json_data={"data": []})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)
    wallhaven.search(["IU"], "mobile", "date_added")
    assert captured["params"]["apikey"] == "test-key"


def test_download_image_returns_bytes(mocker):
    mocker.patch("app.wallhaven.http_client.get", return_value=_FakeResponse(content=b"fake-jpeg-bytes"))
    data = wallhaven.download_image("https://x/abc123.jpg")
    assert data == b"fake-jpeg-bytes"
