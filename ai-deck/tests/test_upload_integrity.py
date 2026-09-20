import io

import upload


def request_upload(folder, data, length):
    handler = object.__new__(upload.Handler)
    handler.headers = {"Content-Length": str(length)}
    handler.rfile = io.BytesIO(data)
    handler._route = lambda: (str(folder), "input.txt")
    replies = []
    handler._reply = lambda code, message="": replies.append((code, message))
    handler.do_PUT()
    return replies


def test_incomplete_upload_preserves_previous_file(tmp_path, monkeypatch):
    monkeypatch.setitem(upload.DIRS, "in", str(tmp_path))
    dest = tmp_path / "input.txt"
    dest.write_text("original")
    assert request_upload(tmp_path, b"partial", 20)[0][0] == 400
    assert dest.read_text() == "original"
    assert list(tmp_path.iterdir()) == [dest]


def test_upload_does_not_follow_part_symlink_and_is_readable(tmp_path, monkeypatch):
    monkeypatch.setitem(upload.DIRS, "in", str(tmp_path))
    protected = tmp_path / "protected"
    protected.write_text("keep")
    (tmp_path / "input.txt.part").symlink_to(protected)
    assert request_upload(tmp_path, b"complete", 8)[0][0] == 201
    assert protected.read_text() == "keep"
    dest = tmp_path / "input.txt"
    assert dest.read_bytes() == b"complete"
    assert dest.stat().st_mode & 0o777 == 0o644


def test_invalid_upload_length_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setitem(upload.DIRS, "in", str(tmp_path))
    for length in (-1, "broken"):
        assert request_upload(tmp_path, b"", length)[0][0] == 400
    assert not list(tmp_path.iterdir())
