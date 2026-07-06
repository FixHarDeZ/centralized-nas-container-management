import os
import zipfile

import pytest

import cbz


def test_build_cbz(tmp_path):
    dest = str(tmp_path / "out.cbz")
    cover = str(tmp_path / "cover.jpg")
    pages, size = cbz.build_cbz(
        [(".jpg", b"one"), (".png", b"two")], dest, cover
    )
    assert pages == 2
    assert size == os.path.getsize(dest)
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["001.jpg", "002.png"]
    assert open(cover, "rb").read() == b"one"
    assert not os.path.exists(dest + ".part")


def test_build_cbz_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        cbz.build_cbz([], str(tmp_path / "o.cbz"), str(tmp_path / "c.jpg"))
