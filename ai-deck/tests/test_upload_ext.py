"""The drawer sends a name without its extension plus X-Upload-Ext; upload.py
joins them back so the file lands under its real name."""
import io
from pathlib import Path

import pytest

import upload

ROOT = Path(__file__).resolve().parents[1]


def handler(path, ext=None, body=b""):
    h = object.__new__(upload.Handler)
    h.path = path
    h.headers = {"Content-Length": str(len(body))}
    if ext is not None:
        h.headers["X-Upload-Ext"] = ext
    h.rfile = io.BytesIO(body)
    h.replies = []
    h._reply = lambda code, message="": h.replies.append((code, message))
    return h


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setitem(upload.DIRS, "in", str(tmp_path))
    return tmp_path


def test_extension_is_put_back_on_upload(inbox):
    h = handler("/upload/in/photo", ".png", b"img")
    h.do_PUT()
    assert h.replies == [(201, "ok")]
    assert (inbox / "photo.png").read_bytes() == b"img"
    assert not (inbox / "photo").exists()


def test_thai_name_and_encoded_extension(inbox):
    h = handler("/upload/in/%E0%B8%A3%E0%B8%B2%E0%B8%A2%E0%B8%87%E0%B8%B2%E0%B8%99%20Q3", ".xlsx", b"x")
    h.do_PUT()
    assert (inbox / "รายงาน Q3.xlsx").read_bytes() == b"x"


def test_no_header_keeps_the_old_behaviour(inbox):
    h = handler("/upload/in/notes.txt", None, b"t")
    h.do_PUT()
    assert (inbox / "notes.txt").read_bytes() == b"t"


def test_delete_with_header_removes_the_real_file(inbox):
    (inbox / "photo.png").write_bytes(b"img")
    h = handler("/upload/in/photo", ".png")
    h.do_DELETE()
    assert not (inbox / "photo.png").exists()


@pytest.mark.parametrize("ext", [
    "png",            # no leading dot
    "./x", ".a/b",    # separator
    ".%2Fetc",        # encoded separator
    ".a\\b",          # backslash
    ".tar.gz",        # second dot
    "..",             # dot-dot
    ".%0Apng",        # control character
    ".abcdefghijklmnop",  # longer than 15 after the dot
    ".",              # nothing after the dot
])
def test_bad_extension_is_rejected(inbox, ext):
    h = handler("/upload/in/photo", ext, b"img")
    assert h._route() == (None, None)
    assert h.replies[0][0] == 400
    assert not list(inbox.iterdir())


def test_double_encoded_separator_stays_literal(inbox):
    # Joined raw and unquoted once: %252F is the three characters %2F, never /.
    h = handler("/upload/in/photo", ".%252F", b"img")
    h.do_PUT()
    assert [p.name for p in inbox.iterdir()] == ["photo.%2F"]


def test_nginx_upload_location_beats_the_static_regex():
    conf = (ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")
    assert "location ^~ /upload/ {" in conf
