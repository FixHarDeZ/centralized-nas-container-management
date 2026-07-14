from xml.etree.ElementTree import Element, SubElement, tostring

import db

ATOM = "http://www.w3.org/2005/Atom"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _feed(feed_id: str, title: str) -> Element:
    feed = Element("feed", xmlns=ATOM)
    SubElement(feed, "id").text = feed_id
    SubElement(feed, "title").text = title
    SubElement(feed, "updated").text = db.now_iso()
    return feed


def _entry(feed: Element, entry_id: str, title: str, updated: str) -> Element:
    entry = SubElement(feed, "entry")
    SubElement(entry, "id").text = entry_id
    SubElement(entry, "title").text = title
    SubElement(entry, "updated").text = updated
    return entry


SECTION_NAMES = {"new": "ใหม่ล่าสุด", "long": "หน้าเยอะ"}


def root_feed(base_url: str = "") -> bytes:
    feed = _feed("ink-reader:root", "ink-reader")
    for section, name in SECTION_NAMES.items():
        path = f"/opds/{section}"
        entry = _entry(feed, f"ink-reader:{path}", name, db.now_iso())
        SubElement(entry, "link", rel="subsection", href=f"{base_url}{path}",
                   type=ACQ_TYPE)
    return tostring(feed, encoding="utf-8", xml_declaration=True)


def titles_feed(section: str, base_url: str = "") -> bytes:
    feed = _feed(f"ink-reader:{section}", SECTION_NAMES.get(section, section))
    rows = db.list_titles(status="new")
    if section == "long":
        min_pages = db.get_settings()["min_pages"]
        rows = [r for r in rows if (r["pages"] or 0) >= min_pages]
    for row in rows:
        entry = _entry(feed, f"ink-reader:title:{row['id']}", row["title"],
                       row["downloaded_at"])
        SubElement(entry, "link", rel="http://opds-spec.org/acquisition",
                   href=f"{base_url}/files/{row['id']}.cbz",
                   type="application/vnd.comicbook+zip")
        SubElement(entry, "link", rel="http://opds-spec.org/thumbnail",
                   href=f"{base_url}/covers/{row['id']}.jpg", type="image/jpeg")
    return tostring(feed, encoding="utf-8", xml_declaration=True)
