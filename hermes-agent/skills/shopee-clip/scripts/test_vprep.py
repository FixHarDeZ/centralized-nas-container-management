import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from PIL import Image

import vprep


def test_big_png_sheet_becomes_a_small_jpeg(tmp_path):
    src = tmp_path / "sheet.png"
    Image.effect_noise((3840, 2160), 64).convert("RGB").save(src)
    dst, size = vprep.prep(str(src))
    assert dst.endswith("sheet.v.jpg") and max(size) == 1600
    assert os.path.getsize(dst) < os.path.getsize(src) / 4


def test_small_jpeg_is_passed_through(tmp_path):
    src = tmp_path / "a.jpg"
    Image.new("RGB", (800, 600), (10, 20, 30)).save(src, "JPEG")
    dst, size = vprep.prep(str(src))
    assert size == (800, 600) and open(dst, "rb").read() == open(src, "rb").read()
