import xml.etree.ElementTree as ET

import db
import opds

ATOM = "{http://www.w3.org/2005/Atom}"


def test_root_feed(data_dir):
    root = ET.fromstring(opds.root_feed())
    hrefs = [l.get("href") for e in root.findall(f"{ATOM}entry")
             for l in e.findall(f"{ATOM}link")]
    assert hrefs == ["/opds/new", "/opds/long"]


def test_root_feed_absolute_urls(data_dir):
    root = ET.fromstring(opds.root_feed("http://192.168.1.100:5068"))
    hrefs = [l.get("href") for e in root.findall(f"{ATOM}entry")
             for l in e.findall(f"{ATOM}link")]
    assert hrefs == ["http://192.168.1.100:5068/opds/new",
                     "http://192.168.1.100:5068/opds/long"]


def test_titles_feed(data_dir):
    tid = db.add_title("s1", "Story One", "a,b", 20, 1000, "u")
    root = ET.fromstring(opds.titles_feed("new"))
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    links = {l.get("rel"): l for l in entries[0].findall(f"{ATOM}link")}
    acq = links["http://opds-spec.org/acquisition"]
    assert acq.get("href") == f"/files/{tid}.cbz"
    assert acq.get("type") == "application/vnd.comicbook+zip"
    assert links["http://opds-spec.org/thumbnail"].get("href") == f"/covers/{tid}.jpg"


def test_titles_feed_absolute_urls(data_dir):
    tid = db.add_title("s1", "Story One", "a,b", 20, 1000, "u")
    base = "http://192.168.1.100:5068"
    root = ET.fromstring(opds.titles_feed("new", base))
    entries = root.findall(f"{ATOM}entry")
    links = {l.get("rel"): l for l in entries[0].findall(f"{ATOM}link")}
    assert links["http://opds-spec.org/acquisition"].get("href") == f"{base}/files/{tid}.cbz"
    assert links["http://opds-spec.org/thumbnail"].get("href") == f"{base}/covers/{tid}.jpg"


def test_long_feed_filters_by_min_pages(data_dir):
    db.add_title("s1", "Short", "", 5, 1, "u")
    tid = db.add_title("s2", "Long", "", 45, 1, "u")
    root = ET.fromstring(opds.titles_feed("long"))
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    assert entries[0].find(f"{ATOM}id").text == f"ink-reader:title:{tid}"
