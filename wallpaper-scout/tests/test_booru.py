import app.booru as booru


class _FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


def _post(pid, w, h, ext="jpg"):
    return {
        "id": pid,
        "width": w,
        "height": h,
        "file_url": f"https://x/{pid}.{ext}",
    }


def test_tag_lowercases_and_underscores():
    assert booru._tag("Wuthering Waves") == "wuthering_waves"
    assert booru._tag("  IU  ") == "iu"


def test_search_namespaces_ids_and_dedups_across_sites(mocker):
    # Same landscape post returned by both sites → two namespaced ids, no clobber.
    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        return _FakeResponse(json_data=[_post(101, 3840, 2160)])

    mocker.patch("app.booru.http_client.get", side_effect=fake_get)
    results = booru.search(["kimono"], "pc", "toplist")
    ids = {r["id"] for r in results}
    assert ids == {"yr:101", "kc:101"}
    assert all(r["path"] == "https://x/101.jpg" for r in results)


def test_search_filters_by_purpose_resolution_and_orientation(mocker):
    # portrait 1080x1920 fits mobile; landscape 3840x2160 does not.
    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        return _FakeResponse(json_data=[_post(1, 1080, 1920), _post(2, 3840, 2160), _post(3, 500, 900)])

    mocker.patch("app.booru.http_client.get", side_effect=fake_get)
    results = booru.search(["x"], "mobile", "date_added")
    # only post 1 passes (2 is landscape, 3 below min res); dedups to one id per site
    kept = {r["id"].split(":")[1] for r in results}
    assert kept == {"1"}


def test_search_maps_sorting_to_moebooru_order(mocker):
    captured = []

    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        captured.append(params["tags"])
        return _FakeResponse(json_data=[])

    mocker.patch("app.booru.http_client.get", side_effect=fake_get)
    booru.search(["x"], "pc", "toplist")
    assert all("order:score" in t for t in captured)
    captured.clear()
    booru.search(["x"], "pc", "date_added")
    assert all("order:id" in t for t in captured)


def test_search_requests_only_safe_rating(mocker):
    captured = []

    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        captured.append(params["tags"])
        return _FakeResponse(json_data=[])

    mocker.patch("app.booru.http_client.get", side_effect=fake_get)
    booru.search(["x"], "pc", "toplist")
    assert all("rating:s" in t for t in captured)


def test_search_survives_one_site_failing(mocker):
    # yande.re raises, konachan.net returns a post → still get the konachan result.
    def fake_get(url, *, params=None, headers=None, timeout=None, **kwargs):
        if "yande.re" in url:
            raise RuntimeError("cloudflare")
        return _FakeResponse(json_data=[_post(9, 3840, 2160)])

    mocker.patch("app.booru.http_client.get", side_effect=fake_get)
    results = booru.search(["x"], "pc", "toplist")
    assert {r["id"] for r in results} == {"kc:9"}


def test_download_image_returns_bytes(mocker):
    mocker.patch("app.booru.http_client.get", return_value=_FakeResponse(content=b"img"))
    assert booru.download_image("https://x/1.jpg") == b"img"
