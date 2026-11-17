"""make_poster_cover.py — run inside the Hermes container (needs Pillow with Raqm):
uv run -q --with pytest --with pillow python -m pytest test_make_poster_cover.py -q"""
import json

import make_poster_cover as mp
import pytest
from PIL import Image, features

pytestmark = pytest.mark.skipif(not features.check("raqm"), reason="Pillow without Raqm")


@pytest.fixture
def spec(tmp_path):
    Image.new("RGB", (720, 1280), (40, 90, 200)).save(tmp_path / "hero.jpg")
    Image.new("RGB", (800, 800), (200, 60, 60)).save(tmp_path / "img.jpg")
    s = {"hero": "hero.jpg", "title": ["น้ำหอมติดช่องแอร์", "แค่คลิป ก็หอม!"], "sub": "เปลี่ยนกลิ่นอับในรถ ให้หอมสดชื่น",
         "badge": ["มี 2 สี", "ฟ้า / ดำ"],
         "circles": [{"image": "img.jpg", "box": [100, 100, 500, 500], "label": f"จุดเด่น {i}"} for i in (1, 2, 3)],
         "chips": ["ติดช่องแอร์", "ดีไซน์คริสตัลใส", "หอมตามลมแอร์"]}
    return tmp_path, s


def run(tmp_path, s):
    (tmp_path / "spec.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return mp.main([str(tmp_path / "spec.json"), "--out", str(tmp_path / "cover.jpg")])


def test_three_circles_make_a_1080x1920_cover(spec):
    tmp, s = spec
    assert run(tmp, s) == 0
    assert Image.open(tmp / "cover.jpg").size == (1080, 1920)


def test_no_circles_no_sub_no_badge_still_builds(spec):
    tmp, s = spec
    s.pop("circles")
    s.pop("sub")
    s.pop("badge")
    s["title"] = "ครีมอาบน้ำ"
    assert run(tmp, s) == 0
    assert Image.open(tmp / "cover.jpg").size == (1080, 1920)


@pytest.mark.parametrize("field,value", [("sub", "ลดราคาวันนี้"), ("chips", ["ซื้อ 1 แถม 1", "หอม"]),
                                         ("badge", ["50%"]), ("title", ["Sale now"])])
def test_price_wording_is_refused(spec, capsys, field, value):
    tmp, s = spec
    s[field] = value
    assert run(tmp, s) == 1
    assert "REFUSED" in capsys.readouterr().err and not (tmp / "cover.jpg").exists()


def test_plain_digits_pass(spec):
    tmp, s = spec
    s["chips"] = ["มี 2 สี", "ขนาด 400 มล.", "8 กลิ่น"]
    assert run(tmp, s) == 0


def test_text_that_cannot_fit_names_the_element(spec, capsys):
    tmp, s = spec
    s["title"] = ["น้ำหอมติดช่องแอร์รถยนต์คริสตัลใสหอมสดชื่นยาวนานทั้งคันทุกครั้งที่ขึ้นรถ"]
    assert run(tmp, s) == 1
    assert "title line 1 does not fit" in capsys.readouterr().err


def test_long_chips_wrap_to_two_rows_and_too_long_fails(spec, capsys):
    tmp, s = spec
    s["chips"] = ["ติดช่องแอร์ได้ทุกรุ่น", "ดีไซน์คริสตัลใสสวยหรู", "หอมตามลมแอร์ทั้งคัน", "มีให้เลือก 2 สี"]
    assert run(tmp, s) == 0
    s["chips"] = ["ก" * 80, "หอม"]
    assert run(tmp, s) == 1
    assert "chips do not fit" in capsys.readouterr().err


def test_bad_box_and_chip_count_are_refused(spec, capsys):
    tmp, s = spec
    s["circles"][0]["box"] = [0, 0, 5000, 5000]
    assert run(tmp, s) == 1
    assert "outside" in capsys.readouterr().err
    s["circles"] = []
    s["chips"] = ["อย่างเดียว"]
    assert run(tmp, s) == 1


def test_theme_auto_follows_the_hero_and_named_theme_is_checked(spec, capsys):
    tmp, s = spec
    blue = mp.palette("auto", Image.new("RGB", (64, 64), (40, 90, 200)))["dark"]
    assert blue[2] > blue[0]                                   # a blue hero gives a blue card
    assert mp.palette("auto", Image.new("RGB", (64, 64), (128, 128, 128)))["dark"] == mp.palette("blue", None)["dark"]
    s["theme"] = "neon"
    assert run(tmp, s) == 1
