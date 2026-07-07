import os

from sources.doujinth import DoujintSource

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


def test_doujinth_parse_listing():
    src = DoujintSource("https://doujin-th.example")
    items = src.parse_listing(_read("listing.html"))
    assert [i["slug"] for i in items] == ["111", "112"]
    assert items[0]["title"] == "เรื่องหนึ่ง"
    assert items[0]["url"] == "https://doujin-th.example/forum/index.php?topic=111.0"
    assert items[1]["title"] == "เรื่องสอง"


def test_doujinth_parse_listing_ignores_links_without_item_class():
    src = DoujintSource("https://doujin-th.example")
    items = src.parse_listing(_read("listing.html"))
    assert "999" not in {i["slug"] for i in items}


def test_doujinth_parse_title_page():
    src = DoujintSource("https://doujin-th.example")
    meta = src.parse_title_page(_read("title.html"))
    assert meta["tags"] == ["tag-a", "tag-b"]
    assert meta["image_urls"] == [
        "https://cdn.example/pages/111-001.jpg",
        "https://cdn.example/pages/111-002.jpg",
    ]


def test_doujinth_parse_title_page_filters_decorative_images():
    src = DoujintSource("https://doujin-th.example")
    meta = src.parse_title_page(_read("title.html"))
    assert not any("/image/other/" in u for u in meta["image_urls"])
