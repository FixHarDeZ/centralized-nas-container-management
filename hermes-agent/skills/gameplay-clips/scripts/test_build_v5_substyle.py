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
