"""chipcheck.py on synthetic chips (real-chip calibration: genme/plaid 2026-11-23, see the docstring).

Run: uv run --with pytest --with numpy --with pillow pytest -q hermes-agent/skills/flow-driver/scripts/test_chipcheck.py
"""
import importlib.util
import json
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("chipcheck", os.path.join(HERE, "chipcheck.py"))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def picture(path, seed, size=(600, 600), tint=None):
    """Blocky random picture; tint swaps the colour of the same layout (a second colourway)."""
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, (12, 12, 3)).astype(np.uint8)
    if tint is not None:
        a = a[:, :, tint]
    Image.fromarray(a).resize(size, Image.NEAREST).save(path)
    return str(path)


def chip_of(src, out, badge=False):
    """What Flow draws: centre square, ~50 px, rounded corners on the dark page, maybe a person badge."""
    im = Image.open(src).convert("RGB")
    im = cc.cover_square(im).resize((100, 100), Image.LANCZOS)
    page = Image.new("RGB", (120, 120), (20, 22, 24))
    mask = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 99, 99), 22, fill=255)
    page.paste(im, (10, 10), mask)
    if badge:
        ImageDraw.Draw(page).rectangle((80, 80, 108, 108), fill=(255, 255, 255))
    page.save(out)
    return str(out)


def run(tmp_path, capsys, chips, expect, pool=()):
    args = sum((["--chip", c] for c in chips), []) + sum((["--expect", e] for e in expect), [])
    args += sum((["--pool", p] for p in pool), [])
    rc = cc.main(args)
    return rc, json.loads(capsys.readouterr().out)


def test_right_chips_pass(tmp_path, capsys):
    ref = picture(tmp_path / "ref1.jpg", 1); face = picture(tmp_path / "char.jpg", 2, (1376, 768))
    other = picture(tmp_path / "other_char.jpg", 3, (1376, 768))
    rc, out = run(tmp_path, capsys, [chip_of(ref, tmp_path / "c1.png"), chip_of(face, tmp_path / "c2.png", badge=True)],
                  [ref, face], [other])
    assert rc == 0 and out["ok"]


def test_wrong_character_is_wrong_not_a_vision_read(tmp_path, capsys):
    ref = picture(tmp_path / "ref1.jpg", 1); face = picture(tmp_path / "char.jpg", 2, (1376, 768))
    other = picture(tmp_path / "other_char.jpg", 3, (1376, 768))
    rc, out = run(tmp_path, capsys, [chip_of(ref, tmp_path / "c1.png"), chip_of(other, tmp_path / "c2.png", True)],
                  [ref, face], [other])
    assert rc == 1 and out["missing"] == ["char.jpg"] and out["chips"][1]["verdict"] == "WRONG"


def test_other_colourway_is_told_apart(tmp_path, capsys):
    blue = picture(tmp_path / "blue.jpg", 5); grey = picture(tmp_path / "grey.jpg", 5, tint=[2, 0, 1])
    rc, out = run(tmp_path, capsys, [chip_of(grey, tmp_path / "c.png")], [blue], [grey])
    assert rc == 1 and out["chips"][0]["verdict"] == "WRONG"


def test_same_picture_at_another_size_is_one_candidate(tmp_path, capsys):
    small = picture(tmp_path / "ref_back.jpg", 7, (304, 342))
    big = str(tmp_path / "ref2.jpg"); Image.open(small).resize((675, 760), Image.LANCZOS).save(big)
    rc, out = run(tmp_path, capsys, [chip_of(small, tmp_path / "c.png")], [big], [small])
    assert rc == 0 and out["chips"][0]["verdict"] == "match"


def test_unlisted_file_is_no_match(tmp_path, capsys):
    ref = picture(tmp_path / "ref1.jpg", 1); stray = picture(tmp_path / "start.jpg", 9)
    rc, out = run(tmp_path, capsys, [chip_of(ref, tmp_path / "c1.png"), chip_of(stray, tmp_path / "c2.png")], [ref])
    assert rc == 1 and out["chips"][1]["verdict"] == "no-match"


def test_shot_with_rects_origin_and_scale(tmp_path, capsys):
    """cdp_shot.py <out> X Y w h S: rects stay CSS px of the page; --origin X,Y --scale S maps them."""
    ref = picture(tmp_path / "ref1.jpg", 1)
    page = Image.new("RGB", (400, 300), (20, 22, 24))
    page.paste(Image.open(chip_of(ref, tmp_path / "c.png")).resize((60, 60)), (200, 150))
    page.crop((180, 130, 300, 230)).resize((480, 400)).save(tmp_path / "row.png")      # X=180 Y=130 S=4
    rects = json.dumps([{"x": 200, "y": 150, "w": 60, "h": 60}])
    assert cc.main(["--shot", str(tmp_path / "row.png"), "--rects", rects, "--origin", "180,130", "--scale", "4",
                    "--expect", ref]) == 0
    capsys.readouterr()
    off = json.dumps([{"x": 185, "y": 135, "w": 20, "h": 20}])                           # inside, but not the chip
    assert cc.main(["--shot", str(tmp_path / "row.png"), "--rects", off, "--origin", "180,130", "--scale", "4",
                    "--expect", ref]) == 4                                             # capture off != attach wrong
    assert "do NOT remove" in json.loads(capsys.readouterr().out)["next"]
