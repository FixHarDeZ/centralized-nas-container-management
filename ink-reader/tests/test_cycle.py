import os

import db
import scraper

LISTING = """
<a class="hentai-item" href="/forum/index.php?topic=1.0" title="Story A - A">Story A</a>
<a class="doujin-item" href="/forum/index.php?topic=2.0" title="Story B - B">Story B</a>
"""
TITLE = """
<div class="col-xs-12 col-md-8">
  <img class="img-responsive" src="/image/other/foo.jpg">
  <img class="img-responsive" src="{image_url}">
  <a class="tag">Tag1</a>
  <a class="tag">Tag2</a>
  <img class="img-responsive" src="/image/other/bar.jpg">
</div>
<div class="reader">
  <div><img src="{image_url}"></div>
</div>
"""


def _fake_fetch(mapping):
    def fetch(url, referer=None):
        for key, value in mapping.items():
            if key in url:
                return value
        raise RuntimeError(f"unexpected {url}")

    return fetch


def test_cycle_with_tombstone_dedup(data_dir):
    # Add title then tombstone it
    db.add_title("1", "A", "", 1, 1, "u")
    db.purge_title("1")  # tombstone
    fetch = _fake_fetch(
        {
            "topic=2.0": TITLE.format(image_url="/i/img1.jpg").encode(),
            "/i/": b"imgdata",
            "doujin-th": LISTING.encode(),
        }
    )
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert {r["slug"] for r in db.list_titles(status="new")} == {"2"}


def test_cycle_title_failure_skips_and_logs(data_dir):
    def fetch(url, referer=None):
        if "/i/" in url:
            return b"imgdata"
        if "topic=1.0" in url:
            raise RuntimeError("boom")
        if "topic=2.0" in url:
            return TITLE.format(image_url="/i/img1.jpg").encode()
        if "doujin-th" in url:
            return LISTING.encode()
        raise RuntimeError(f"unexpected {url}")

    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert len(result["errors"]) == 1
    assert "1" in result["errors"][0]
    assert db.last_scrape()["error"] is not None
    # story 1 left no row, retried next cycle
    assert "1" not in db.known_slugs()


def test_cycle_respects_max_per_cycle(data_dir, monkeypatch):
    import config

    monkeypatch.setattr(config, "MAX_NEW_PER_CYCLE", 1)
    fetch = _fake_fetch(
        {
            "topic=1.0": TITLE.format(image_url="/i/img1.jpg").encode(),
            "/i/": b"imgdata",
            "doujin-th": LISTING.encode(),
        }
    )
    result = scraper.scrape_cycle(fetch=fetch)
    assert result["downloaded"] == 1
    assert result["found"] == 2
