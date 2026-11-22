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


# ---- detail-slot gates (Fix 2026-11-18: blurry D2 circles, GT6 map not visible, Lego case art cut off)

def test_small_crop_would_be_upscaled_and_is_refused(spec, capsys):
    tmp, s = spec
    s["circles"] = [{"image": "img.jpg", "box": [100, 100, 270, 300], "label": "สายถัก"},
                    {"image": "img.jpg", "box": [0, 0, 400, 400], "label": "มุมข้าง"}]
    assert run(tmp, s) == 1
    err = capsys.readouterr().err
    assert "circle 1 ('สายถัก') is too small" in err and "upscaled" in err


def test_tall_picture_in_a_circle_is_refused_and_a_card_shows_it_whole(spec, capsys):
    tmp, s = spec
    Image.new("RGB", (832, 1400), (200, 30, 30)).save(tmp / "case.jpg")
    s["circles"] = [{"image": "case.jpg", "label": "ปกเกม"}]
    assert run(tmp, s) == 1
    assert "square-ish" in capsys.readouterr().err
    s["circles"][0]["shape"] = "card"
    assert run(tmp, s) == 0
    out = Image.open(tmp / "cover.jpg")
    assert out.size == (1080, 1920)


def test_card_keeps_the_whole_picture(spec):
    tmp, s = spec
    case = Image.new("RGB", (600, 1000), (30, 160, 30))
    case.paste((250, 220, 20), (0, 0, 600, 80))             # a yellow top strip = the title of the case
    case.paste((20, 60, 230), (0, 920, 600, 1000))          # a blue bottom strip
    case.save(tmp / "case.png")
    s["circles"] = [{"image": "case.png", "shape": "card", "label": "ปกเกม"}]
    s["theme"] = "green"
    tmp_out = tmp / "cover.png"
    (tmp / "spec.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    assert mp.main([str(tmp / "spec.json"), "--out", str(tmp_out)]) == 0
    px = [c for _, c in Image.open(tmp_out).convert("RGB").getcolors(1 << 24)]
    near = lambda c, t: max(abs(a - b) for a, b in zip(c, t)) < 40          # noqa: E731
    assert any(near(p, (250, 220, 20)) for p in px)         # both strips survive: nothing was cropped off
    assert any(near(p, (20, 60, 230)) for p in px)


def test_white_and_black_borders_are_trimmed():
    im = Image.new("RGB", (800, 1400), (255, 255, 255))
    im.paste((200, 30, 30), (0, 0, 800, 1250))
    assert mp.trim_border(im).size == (800, 1250)
    im = Image.new("RGB", (1000, 600), (0, 0, 0))
    im.paste((40, 90, 200), (100, 0, 900, 600))
    assert mp.trim_border(im).size == (800, 600)
    plain = Image.new("RGB", (300, 300), (40, 90, 200))
    assert mp.trim_border(plain).size == (300, 300)


def test_long_label_fails_instead_of_turning_tiny(spec, capsys):
    tmp, s = spec
    s["circles"][0]["label"] = "แผนที่สนามกอล์ฟบนข้อมือแบบละเอียดทุกหลุม"
    assert run(tmp, s) == 1
    assert "circle 1 label does not fit" in capsys.readouterr().err


def test_unknown_shape_is_refused(spec, capsys):
    tmp, s = spec
    s["circles"][0]["shape"] = "hexagon"
    assert run(tmp, s) == 1
    assert "shape must be" in capsys.readouterr().err


def test_one_check_sheet_carries_the_cover_and_every_slot(spec, capsys):
    """2026-11-19..22: 47 cover vision calls / ~99 min for 11 covers — one sheet, one call."""
    tmp, s = spec
    assert run(tmp, s) == 0
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    sheet = Image.open(res["check_sheet"])
    assert res["check_sheet"].endswith("cover_sheet.jpg") and sheet.height == mp.SHEET_H
    n = len(s["circles"])
    assert sheet.width > 1080 * mp.SHEET_H // 1920 + n * mp.TILE
    assert f"Pictures 2-{n + 1}" in res["ask_vision"] and res["slot_labels"] == [c["label"] for c in s["circles"]]
