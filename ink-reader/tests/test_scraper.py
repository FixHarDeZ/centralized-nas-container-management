import os

import scraper

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


def test_parse_listing():
    items = scraper.parse_listing(_read("listing.html"), "https://doujin-th.example")
    assert [i["slug"] for i in items] == ["111", "112"]
    assert items[0]["title"] == "เรื่องหนึ่ง"
    assert items[0]["url"] == "https://doujin-th.example/forum/index.php?topic=111.0"
    assert items[1]["title"] == "เรื่องสอง"


def test_parse_listing_ignores_links_without_item_class():
    items = scraper.parse_listing(_read("listing.html"), "https://doujin-th.example")
    assert "999" not in {i["slug"] for i in items}


def test_parse_title_page():
    meta = scraper.parse_title_page(_read("title.html"), "https://doujin-th.example")
    assert meta["tags"] == ["tag-a", "tag-b"]
    assert meta["image_urls"] == [
        "https://cdn.example/pages/111-001.jpg",
        "https://cdn.example/pages/111-002.jpg",
    ]


def test_parse_title_page_filters_decorative_images():
    meta = scraper.parse_title_page(_read("title.html"), "https://doujin-th.example")
    assert not any("/image/other/" in u for u in meta["image_urls"])
