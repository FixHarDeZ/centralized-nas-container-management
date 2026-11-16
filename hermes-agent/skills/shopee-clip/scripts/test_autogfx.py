"""Unit tests for autogfx.py's layout maths (numpy only: no ffmpeg, no OpenCV).

Run: uv run --with pytest --with numpy pytest -q hermes-agent/skills/shopee-clip/scripts/test_autogfx.py
"""
import importlib.util
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("autogfx", os.path.join(HERE, "autogfx.py"))
ag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ag)

FACE = [250, 300, 470, 560]


def wall(free):
    """A 180x320 busy mask that is busy everywhere except the rect `free` (720x1280 px coords)."""
    m = np.ones((ag.H // ag.S, ag.W // ag.S), np.uint8)
    m[free[1] // ag.S:free[3] // ag.S, free[0] // ag.S:free[2] // ag.S] = 0
    return m


def test_hook_card_stays_inside_the_wall_with_its_slide_and_border():
    c = ag.hook_fit([500, 260, 720, 640], aspect=0.55)
    w = 0.55 * c["h"] + 42
    assert c["x"] - w / 2 >= 500 and c["x"] + w / 2 <= 715
    top = c["y"] - (c["h"] + 42) / 2
    assert top - 6 >= 260 and top + c["h"] + 42 + 46 <= 640
    assert ag.hook_fit([600, 260, 720, 640], aspect=1.0) is None        # 115 px of wall: the width binds
    assert ag.hook_fit(None, 0.55) is None


def test_hook_takes_the_last_window_that_still_fits():
    big, small = [480, 260, 720, 640], [640, 260, 720, 640]
    probes = [{"window": [0, 1.4], "empty_left": None, "empty_right": big},
              {"window": [0, 2.0], "empty_left": None, "empty_right": big},
              {"window": [0, 2.5], "empty_left": None, "empty_right": small},
              {"window": [0, 3.0], "empty_left": None, "empty_right": big}]     # after a miss nothing counts
    dur, card = ag.pick_hook(probes, 0.55)
    assert dur == 2.0 and card["h"] >= ag.HOOK_MIN_H
    assert ag.pick_hook(probes[2:], 0.55) is None


def test_windows_keep_clear_of_the_seam_and_the_end():
    wins = ag.scene_windows({"v_dur": 15.83, "scenes": [{"global_start": 0.0}, {"global_start": 7.79}]})
    assert [w[0] for w in wins] == [0, 0, 0, 1, 1, 1]
    assert wins[2][2] <= 7.49 and wins[3][1] >= 8.09 and wins[-1][2] <= 15.33
    assert all(c1 - c0 <= ag.CHUNK + 0.01 for _, c0, c1 in wins)


def test_sticker_goes_on_free_wall_and_never_on_the_face():
    spot = ag.free_spot(wall([480, 280, 720, 480]), [ag.pad(FACE, 30)], FACE)
    assert 528 <= spot[0] <= 672 and 328 <= spot[1] <= 432
    assert ag.free_spot(wall([0, 0, 0, 0]), [ag.pad(FACE, 30)], FACE) is None       # a real room: no wall at all
    x, y = ag.side_spot([100, 300, 320, 560])                                       # then: the roomier side
    assert x > 320 and ag.ZONE[1] <= y <= ag.ZONE[3]


def test_plan_has_an_avoid_per_window_and_a_cta_arrow_at_the_end():
    wins = [{"scene": 0, "t0": 0.1, "t1": 2.5, "face": FACE, "busy": wall([480, 280, 720, 680])},
            {"scene": 0, "t0": 2.5, "t1": 5.0, "face": None, "busy": wall([480, 280, 720, 680])},
            {"scene": 1, "t0": 8.1, "t1": 10.5, "face": FACE, "busy": wall([0, 0, 0, 0])},      # product fills it
            {"scene": 1, "t0": 10.5, "t1": 15.3, "face": FACE, "busy": wall([0, 440, 200, 700])}]
    plan, skipped = ag.plan_gfx(wins)
    assert any("8.1-10.5s: no free wall" in s for s in skipped) and len(plan["stickers"]) == 3
    assert len(plan["avoid"]) == 4 and plan["avoid"][1]["rect"] == plan["avoid"][0]["rect"]   # inherited box
    assert any("no face" in s for s in skipped)
    assert plan["stickers"][-1]["kind"] == "arrow" and plan["stickers"][-1]["y"] >= 480
    for st in plan["stickers"]:
        r = (st["x"] - 28, st["y"] - 28, st["x"] + 28, st["y"] + 28)
        for av in plan["avoid"]:
            assert not (st["start"] < av["end"] and av["start"] < st["end"] and ag.overlap(r, av["rect"]))
    assert all("busy" not in str(plan) and "_face" not in w for w in wins)


def test_a_sticker_keeps_off_the_hook_card_while_it_shows():
    wins = [{"scene": 0, "t0": 0.1, "t1": 2.5, "face": FACE, "busy": wall([480, 280, 720, 680])},
            {"scene": 0, "t0": 2.5, "t1": 5.0, "face": FACE, "busy": wall([480, 280, 720, 680])},
            {"scene": 0, "t0": 5.0, "t1": 7.5, "face": FACE, "busy": wall([480, 280, 720, 680])}]
    hook = {"end": 2.4, "rect": [480, 280, 720, 520]}
    plan, _ = ag.plan_gfx(wins, hook)
    first = plan["stickers"][0]
    assert not ag.overlap((first["x"] - 28, first["y"] - 28, first["x"] + 28, first["y"] + 28), hook["rect"])


def test_nothing_measured_free_means_no_sticker_and_a_warning():
    wins = [{"scene": 0, "t0": 0.1, "t1": 2.5, "face": FACE, "busy": wall([0, 0, 0, 0])},
            {"scene": 0, "t0": 2.5, "t1": 5.0, "face": FACE, "busy": wall([0, 0, 0, 0])}]
    plan, skipped = ag.plan_gfx(wins)
    assert plan["stickers"] == [] and "NO sticker placed" in skipped[-1]
    plan, _ = ag.plan_gfx([{"scene": 0, "t0": 0.1, "t1": 2.5, "face": [100, 300, 320, 560], "busy": None}])
    assert plan["stickers"][0]["x"] > 360                               # unmeasured: beside the face
