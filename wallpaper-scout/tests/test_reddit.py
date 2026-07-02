import pytest

import app.reddit as reddit


class _FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def _creds_and_fresh_token(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    reddit._token["value"] = None
    reddit._token["exp"] = 0.0


def _post(pid, w, h, over_18=False):
    return {
        "data": {
            "id": pid,
            "over_18": over_18,
            "preview": {"images": [{"source": {"url": f"https://preview.redd.it/{pid}.jpg?width={w}&s=x", "width": w, "height": h}}]},
        }
    }


def _listing(*posts):
    return _FakeResponse(json_data={"data": {"children": list(posts)}})


def test_search_returns_empty_when_creds_unset(monkeypatch, mocker):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    get = mocker.patch("app.reddit.http_client.get")
    assert reddit.search(["IU"], "mobile", "toplist") == []
    get.assert_not_called()


def test_search_fetches_token_then_searches_and_filters(mocker):
    post_mock = mocker.patch(
        "app.reddit.http_client.post",
        return_value=_FakeResponse(json_data={"access_token": "tok", "expires_in": 3600}),
    )
    # p1 portrait fits mobile; p2 landscape doesn't; p3 over_18 excluded
    mocker.patch(
        "app.reddit.http_client.get",
        return_value=_listing(_post("p1", 1080, 1920), _post("p2", 3840, 2160), _post("p3", 1080, 1920, over_18=True)),
    )
    results = reddit.search(["IU"], "mobile", "toplist")
    assert {r["id"] for r in results} == {"rd:p1"}
    assert results[0]["path"].startswith("https://preview.redd.it/p1.jpg")
    # token obtained via client_credentials + basic auth
    assert post_mock.call_args.kwargs["data"] == {"grant_type": "client_credentials"}
    assert post_mock.call_args.kwargs["auth"] == ("cid", "secret")


def test_token_is_cached_across_calls(mocker):
    post_mock = mocker.patch(
        "app.reddit.http_client.post",
        return_value=_FakeResponse(json_data={"access_token": "tok", "expires_in": 3600}),
    )
    mocker.patch("app.reddit.http_client.get", return_value=_listing())
    reddit.search(["IU"], "mobile", "toplist")
    reddit.search(["IU2"], "pc", "date_added")
    post_mock.assert_called_once()  # token reused, not refetched


def test_sort_maps_toplist_and_date_added(mocker):
    mocker.patch("app.reddit.http_client.post", return_value=_FakeResponse(json_data={"access_token": "t", "expires_in": 3600}))
    captured = []

    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        captured.append(params["sort"])
        return _listing()

    mocker.patch("app.reddit.http_client.get", side_effect=fake_get)
    reddit.search(["x"], "pc", "toplist")
    reddit.search(["x"], "pc", "date_added")
    assert captured == ["top", "new"]


def test_search_survives_one_term_failing(mocker):
    mocker.patch("app.reddit.http_client.post", return_value=_FakeResponse(json_data={"access_token": "t", "expires_in": 3600}))

    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        if params["q"] == "bad":
            raise RuntimeError("429")
        return _listing(_post("ok1", 1080, 1920))

    mocker.patch("app.reddit.http_client.get", side_effect=fake_get)
    results = reddit.search(["bad", "good"], "mobile", "toplist")
    assert {r["id"] for r in results} == {"rd:ok1"}


def test_download_image_returns_bytes(mocker):
    mocker.patch("app.reddit.http_client.get", return_value=_FakeResponse(content=b"img"))
    assert reddit.download_image("https://preview.redd.it/x.jpg?s=y") == b"img"
