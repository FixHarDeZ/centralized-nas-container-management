import os

import db
import scraper

LISTING = """
<a class="hentai-item" href="/forum/index.php?topic=1.0" title="Story A - A">Story A</a>
<a class="doujin-item" href="/forum/index.php?topic=2.0" title="Story B - B">Story B</a>
"""
TITLE = """
<div class="col-xs-12 col-md-8">
<h1 class="panel-title">{title}</h1>
<p>Tags: <span class="label label-info"><a class="tag" href="#">x</a></span></p>
<img class="img-responsive" src="/i/{slug}/1.jpg">
<img class="img-responsive" src="/i/{slug}/2.jpg">
</div>
"""
EMPTY_LISTING = "<html><body></body></html>"


def _fake_fetch(pages):
    """Fetch stub: matches URL by substring. Returns empty listing for unmatched sources."""
    def fetch(url, referer=None):
        for key, val in pages.items():
            if key in url:
                return val() if callable(val) else val
        # Return empty listing for unknown source URLs to avoid errors
        if "hentaithai" in url or "miku-doujin" in url:
            return EMPTY_LISTING.encode()
        raise RuntimeError(f"unexpected url {url}")
    return fetch


def test_cycle_downloads_new_titles(data_dir, monkeypatch):
    import config
    monkeypatch.setattr(config, "LISTING_PAGES", 1)
    fetch = _fake_fetch({
        "topic=1.0": TITLE.format(title="Story A", slug="1").encode(),
        "topic=2.0": TITLE.format(title="Story B", slug="2").encode(),
        "/i/": b"imgdata",
        "doujin-th": LISTING.encode(),
    })
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 2
    rows = db.list_titles()
    slugs = {r["slug"] for r in rows}
    assert "doujinth-1" in slugs
    assert "doujinth-2" in slugs
    for r in rows:
        assert r["source"] == "doujinth"
        assert r["pages"] == 2
        assert os.path.exists(db.cbz_path(r["id"]))
        assert os.path.exists(db.cover_path(r["id"]))
    assert db.last_scrape()["downloaded"] == 2


def test_cycle_skips_known_and_tombstones(data_dir, monkeypatch):
    import config
    monkeypatch.setattr(config, "LISTING_PAGES", 1)
    tid = db.add_title("doujinth-1", "A", "", 1, 1, "u", source="doujinth")
    db.purge_title(tid)  # tombstone
    fetch = _fake_fetch({
        "topic=2.0": TITLE.format(title="Story B", slug="2").encode(),
        "/i/": b"imgdata",
        "doujin-th": LISTING.encode(),
    })
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert {r["slug"] for r in db.list_titles(status="new")} == {"doujinth-2"}


def test_cycle_title_failure_skips_and_logs(data_dir, monkeypatch):
    import config
    monkeypatch.setattr(config, "LISTING_PAGES", 1)
    def fetch(url, referer=None):
        if "topic=1.0" in url:
            raise RuntimeError("boom")
        if "topic=2.0" in url:
            return TITLE.format(title="Story B", slug="2").encode()
        if "/i/" in url:
            return b"imgdata"
        if "doujin-th" in url:
            return LISTING.encode()
        if "hentaithai" in url or "miku-doujin" in url:
            return EMPTY_LISTING.encode()
        raise RuntimeError(f"unexpected {url}")

    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    # Only doujinth errors (new sources return empty listing, no errors)
    doujinth_errors = [e for e in result["errors"] if e.startswith("doujinth/")]
    assert len(doujinth_errors) == 1
    assert "doujinth/1" in doujinth_errors[0]
    assert db.last_scrape()["error"] is not None
    assert "doujinth-1" not in db.known_slugs()


def test_cycle_respects_max_per_cycle(data_dir, monkeypatch):
    import config
    monkeypatch.setattr(config, "MAX_NEW_PER_CYCLE", 1)
    fetch = _fake_fetch({
        "topic=1.0": TITLE.format(title="Story A", slug="1").encode(),
        "/i/": b"imgdata",
        "doujin-th": LISTING.encode(),
    })
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    # Only doujinth found count (new sources return empty listing)
    assert result["found"] >= 2  # at least doujinth's 2 items
