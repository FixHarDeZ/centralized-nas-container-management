import xml.etree.ElementTree as ET

import db
import opds

ATOM = "{http://www.w3.org/2005/Atom}"


def test_root_feed(data_dir):
    root = ET.fromstring(opds.root_feed())
    hrefs = [l.get("href") for e in root.findall(f"{ATOM}entry")
             for l in e.findall(f"{ATOM}link")]
    assert hrefs == ["/opds/new", "/opds/kept"]


def test_titles_feed(data_dir):
    tid = db.add_title("s1", "Story One", "a,b", 20, 1000, "u")
    root = ET.fromstring(opds.titles_feed("new"))
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    links = {l.get("rel"): l for l in entries[0].findall(f"{ATOM}link")}
    acq = links["http://opds-spec.org/acquisition"]
    assert acq.get("href") == f"/files/{tid}.cbz"
    assert acq.get("type") == "application/vnd.comicbook+zip"
    assert links["http://opds-spec.org/image"].get("href") == f"/covers/{tid}.jpg"


def test_titles_feed_filters_status(data_dir):
    db.add_title("s1", "One", "", 1, 1, "u")
    root = ET.fromstring(opds.titles_feed("kept"))
    assert root.findall(f"{ATOM}entry") == []
