"""sub_style default gate: subs must land in the v5 band (y700-835).

A source .ass carrying the old v4 MarginV 290 put the subs at y~945-1014, outside the
SUB_BAND graphics_layer checks stickers against — so a game-cover sticker placed
"below the subs" silently covered them (Ratatan clip, 2026-11-11). write_subs must
apply the v5 default even when plan.json has no sub_style, and plan.sub_style must
still override it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_v5 as b  # noqa: E402
from build_v5 import SUB_STYLE_V5, write_subs  # noqa: E402

SRC_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Itim,48,&H0066D1FF,&H0066D1FF,&H00203050,&H60203050,1,0,0,0,100,100,0,0,1,5,2.5,2,50,50,290,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.25,0:00:02.61,Sub,,0,0,0,,เกมนี้มาจากคนทำ Patapon
"""


def _run(tmp_path, plan):
    src = tmp_path / "in.ass"
    dst = tmp_path / "out.ass"
    src.write_text(SRC_ASS, encoding="utf-8")
    ev = write_subs(str(src), str(dst), plan, [])
    return dst.read_text(encoding="utf-8"), ev


def test_default_marginv_is_v5(tmp_path):
    out, ev = _run(tmp_path, {})
    style = [ln for ln in out.splitlines() if ln.startswith("Style: ")][0]
    assert style.split(",")[-2] == str(SUB_STYLE_V5["MarginV"]), \
        f"plan without sub_style must get MarginV {SUB_STYLE_V5['MarginV']}, got: {style}"
    assert len(ev) == 1


def test_plan_sub_style_overrides_default(tmp_path):
    out, _ = _run(tmp_path, {"sub_style": {"MarginV": 500}})
    style = [ln for ln in out.splitlines() if ln.startswith("Style: ")][0]
    assert style.split(",")[-2] == "500"


def test_default_band_matches_graphics_layer(tmp_path):
    # SUB_BAND in graphics_layer.py is (0, 700, 720, 835): with MarginV 465 and
    # font 48 the text baseline sits at 1280-465=815 -> text ~y767-815, inside it.
    out, _ = _run(tmp_path, {})
    margin_v = int([ln for ln in out.splitlines()
                    if ln.startswith("Style: ")][0].split(",")[-2])
    baseline = 1280 - margin_v
    text_top = baseline - 48
    assert 700 <= text_top and baseline <= 835, \
        f"MarginV {margin_v} puts text y{text_top}-{baseline}, outside SUB_BAND 700-835"


def test_tall_window_crop_width():
    """window_h 720 shows a 1080 px square of the 1080p source; the 16:9 band shows all 1920."""
    import build_v5
    old = build_v5.WH
    try:
        build_v5.WH = 720
        assert build_v5.tall_crop_w() == 1080
        build_v5.WH = build_v5.BAND_H
        assert build_v5.tall_crop_w() == 1920
    finally:
        build_v5.WH = old


def test_endcard_seg_must_be_wide_and_from_the_full_frame():
    """ffr-swt-dec04 / sniper-elite3-sw 2026-11-20/21: end-card titles cut."""
    assert "wide" in b.endcard_problem({"src": "trailer", "endcard": True}, "/w")
    assert b.endcard_problem({"src": "trailer", "endcard": True, "wide": True}, "/w") is None
    assert "836 px" in b.endcard_problem({"src": "endcard.mp4", "wide": True}, "/w", size=(836, 470))
    assert b.endcard_problem({"src": "/x/trailer_launch.mp4", "wide": True}, "/w", size=(1920, 1080)) is None
    assert b.endcard_problem({"src": "master", "mode": "window"}, "/w") is None


def test_wide_on_a_non_16_9_file_is_refused():
    """switch2-oblivion-rd 2026-11-22: a 1920x600 cut as `wide` was stretched 1.8x into the 720x405 band."""
    why = b.endcard_problem({"src": "endcard.mp4", "endcard": True, "wide": True}, "/w", size=(1920, 600))
    assert "stretch" in why and "crop" in why
    assert b.endcard_problem({"src": "card4k.mp4", "wide": True}, "/w", size=(3840, 2160)) is None


def test_endcard_crop_rules():
    old = b.WH
    try:
        b.WH = 720                                    # tall 1:1 window
        ok = {"src": "trailer", "endcard": True, "crop": [545, 55, 840, 565]}
        assert b.endcard_problem(ok, "/w", (1920, 1080)) is None
        assert "endcard" in b.endcard_problem({"src": "trailer", "crop": [0, 0, 1920, 600]}, "/w", (1920, 1080))
        assert "master" in b.endcard_problem({"src": "master", "endcard": True, "crop": [0, 0, 720, 405]}, "/w")
        assert "leaves" in b.endcard_problem(dict(ok, crop=[1500, 0, 840, 565]), "/w", (1920, 1080))
        assert "narrower" in b.endcard_problem(dict(ok, crop=[0, 0, 400, 600]), "/w", (1920, 1080))
        assert "four ints" in b.endcard_problem(dict(ok, crop=[0, 0, 840.5, 565]), "/w", (1920, 1080))
        b.WH = b.BAND_H                               # 16:9 band: a square crop is too narrow there
        assert "narrower" in b.endcard_problem(dict(ok, crop=[0, 0, 840, 565]), "/w", (1920, 1080))
        assert b.crop_h([0, 0, 1920, 600]) == 224
    finally:
        b.WH = old


def test_endcard_relative_src_resolves_against_the_plan_dir(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(b, "probe_wh", lambda path: seen.append(path) or (836, 470))
    assert "836 px" in b.endcard_problem({"src": "endcard.mp4", "wide": True}, str(tmp_path))
    assert seen == [os.path.join(str(tmp_path), "endcard.mp4")]
    monkeypatch.setattr(b, "probe_wh", lambda path: None)          # unreadable: no verdict, no crash
    assert b.endcard_problem({"src": "gone.mp4", "wide": True}, str(tmp_path)) is None


def test_wash_frames_finds_the_white_flash_only():
    """switch2-oblivion-rd trailer 78.19-78.39 s, measured: 205/13, 232/5.5, 250/1.4, 255/0, 251/1, 234/3.9, 209/9."""
    means = [120, 205.1, 231.9, 250.3, 255.0, 250.6, 233.9, 209.3, 120, 229.9]
    stds = [40, 13.0, 5.5, 1.4, 0.0, 1.0, 3.9, 9.1, 40, 20.2]     # last: a bright frame WITH detail (12.20 s)
    assert b.wash_frames(means, stds, 78.154, 30) == [78.221, 78.254, 78.287, 78.321, 78.354]
