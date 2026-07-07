import os

from sources.doujinth import DoujintSource
from sources.hentaithai import HentaiThaiSource
from sources.mikudoujin import MikuDoujinSource

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    return open(os.path.join(FIXTURES, name), encoding="utf-8").read()


# --- doujinth ---

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


# --- hentaithai ---

def test_hentaithai_parse_listing():
    src = HentaiThaiSource("https://hentaithai.net")
    items = src.parse_listing(_read("hentaithai_listing.html"))
    slugs = [i["slug"] for i in items]
    assert "50579" in slugs
    assert "50578" in slugs
    item = next(i for i in items if i["slug"] == "50579")
    assert item["title"] == "สายสัมพันธ์ที่เหนื่อยล้า"
    assert "t50579" in item["url"]


def test_hentaithai_parse_listing_skips_tag_links():
    src = HentaiThaiSource("https://hentaithai.net")
    items = src.parse_listing(_read("hentaithai_listing.html"))
    slugs = {i["slug"] for i in items}
    assert "tag" not in slugs


def test_hentaithai_parse_title_page():
    src = HentaiThaiSource("https://hentaithai.net")
    meta = src.parse_title_page(_read("hentaithai_title.html"))
    assert "hina-sorasaki" in meta["tags"]
    assert "kuriame kururu" in meta["tags"]
    assert len(meta["image_urls"]) == 3
    assert all("hentaithai.net/image/2026/" in u for u in meta["image_urls"])


def test_hentaithai_parse_title_page_filters_decorative():
    src = HentaiThaiSource("https://hentaithai.net")
    meta = src.parse_title_page(_read("hentaithai_title.html"))
    assert not any("/other/" in u for u in meta["image_urls"])
    assert not any("/sticker/" in u for u in meta["image_urls"])


def test_hentaithai_listing_url():
    src = HentaiThaiSource("https://hentaithai.net")
    assert src.listing_url(1) == "https://hentaithai.net/"
    assert src.listing_url(5) == "https://hentaithai.net/page-5"


# --- mikudoujin ---

def test_mikudoujin_parse_listing():
    src = MikuDoujinSource("https://miku-doujin.com")
    items = src.parse_listing(_read("mikudoujin_listing.html"))
    slugs = [i["slug"] for i in items]
    assert "r-vp2" in slugs
    assert "f-hkc" in slugs
    item = next(i for i in items if i["slug"] == "r-vp2")
    assert item["title"] == "ความลับเล็กๆระหว่างเรานะ r-vp2"
    assert item["url"] == "https://miku-doujin.com/r-vp2/"


def test_mikudoujin_parse_listing_skips_non_content():
    src = MikuDoujinSource("https://miku-doujin.com")
    items = src.parse_listing(_read("mikudoujin_listing.html"))
    slugs = {i["slug"] for i in items}
    assert "page" not in slugs


def test_mikudoujin_parse_title_page():
    src = MikuDoujinSource("https://miku-doujin.com")
    meta = src.parse_title_page(_read("mikudoujin_title.html"))
    assert "นมใหญ่" in meta["tags"]
    assert "นักเรียน" in meta["tags"]
    # Title page has no direct images, only episode URLs
    assert meta["image_urls"] == []
    assert len(meta["episode_urls"]) == 2
    ep_slugs = [u.split("/")[-2] for u in meta["episode_urls"]]
    assert "ep-2" in ep_slugs
    assert "ep-1" in ep_slugs


def test_mikudoujin_parse_episode_page():
    src = MikuDoujinSource("https://miku-doujin.com")
    meta = src.parse_episode_page(_read("mikudoujin_episode.html"))
    assert len(meta["image_urls"]) == 3
    assert all("miku-doujin.com/uploads/" in u for u in meta["image_urls"])


def test_mikudoujin_needs_episode_fetch():
    src = MikuDoujinSource("https://miku-doujin.com")
    assert src.needs_episode_fetch is True


def test_mikudoujin_listing_url():
    src = MikuDoujinSource("https://miku-doujin.com")
    assert src.listing_url(1) == "https://miku-doujin.com/"
    assert src.listing_url(3) == "https://miku-doujin.com/page/3/"


def test_mikudoujin_parse_lazy_images():
    """Title pages use img.lazy[data-src] instead of img.page-img[src]."""
    src = MikuDoujinSource("https://miku-doujin.com")
    meta = src.parse_title_page(_read("mikudoujin_title_lazy.html"))
    assert len(meta["image_urls"]) == 2
    assert all("miku-doujin.com/uploads/" in u for u in meta["image_urls"])
    assert meta["episode_urls"] == []
