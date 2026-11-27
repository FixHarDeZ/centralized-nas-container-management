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


# ---- board-named beats / elements (huawei-watchfit5 2026-11-23: 73 min of hand geometry)
def test_parse_span_and_spread():
    assert ag.parse_span("4.4-6.4:product") == (4.4, 6.4, "product")
    assert ag.parse_span("4.4-6.4", "auto") == (4.4, 6.4, "auto")
    (c, far) = ag.spread([(100, 100), (110, 100), (100, 120)])
    assert c == (100, 100) and round(far) == 20
    try:
        ag.parse_span("6-4")
        assert False
    except ValueError:
        pass


def test_image_fits_on_free_wall_first():
    fit = ag.fit_image(wall([440, 262, 720, 700]), FACE, 1.0, [ag.RAIL])
    h, cx, cy, how = fit
    r = ag.image_rect(cx, cy, h, 1.0)
    assert how == "free wall" and r[0] >= 440 and r[3] <= ag.SUB_TOP and r[1] >= ag.PILL_BOTTOM
    assert not ag.overlap(r, ag.RAIL)


def test_image_goes_beside_the_face_in_a_busy_room():
    busy = np.ones((ag.H // ag.S, ag.W // ag.S), np.uint8)
    h, cx, cy, how = ag.fit_image(busy, FACE, 1.0, [ag.RAIL])
    r = ag.image_rect(cx, cy, h, 1.0)
    assert how == "beside face" and h >= 110
    assert not ag.overlap(r, ag.pad(FACE, 20)) and not ag.overlap(r, [FACE[0] - 20, FACE[1], FACE[2] + 20, ag.H])
    assert r[3] <= ag.SUB_TOP


def test_no_room_means_no_sticker():
    face = [60, 300, 660, 640]                     # a close-up: the face fills the band
    busy = np.ones((ag.H // ag.S, ag.W // ag.S), np.uint8)
    assert ag.fit_image(busy, face, 1.0, [ag.RAIL]) is None
    entry, note = ag.place_product_sticker([{"t0": 11.1, "t1": 13.7, "face": face, "busy": busy}],
                                           "ref.jpg", 1.0, 11.0, 20.0)
    assert entry is None and "left out" in note


def test_product_sticker_picks_the_window_where_it_is_biggest():
    busy = np.ones((ag.H // ag.S, ag.W // ag.S), np.uint8)
    wins = [{"t0": 11.1, "t1": 13.7, "face": [60, 300, 660, 640], "busy": busy},
            {"t0": 13.7, "t1": 16.3, "face": FACE, "busy": busy},
            {"t0": 2.0, "t1": 4.6, "face": [500, 300, 700, 500], "busy": busy}]       # outside --sticker-at
    entry, note = ag.place_product_sticker(wins, "ref.jpg", 1.0, 11.0, 20.0)
    assert entry["start"] == 13.9 and entry["end"] == 16.3 and entry["w_est"] == entry["h"]


def rect_fn(text, size, y):
    w = len(text) * size * 0.5
    return (360 - w / 2, y, 360 + w / 2, y + size * 1.3 + 12)


def test_headline_clears_face_pill_and_sub_bands():
    faces = [(8.0, 10.5, [200, 150, 540, 580])]
    entry, note = ag.place_headline("No Phone", 8.5, 10.4, faces, [[8.0, 9.0, "x"]], [[8.4, 10.0, "s"]], rect_fn)
    r = rect_fn(entry["text"], entry["size"], entry["y"])
    assert not ag.overlap(r, faces[0][2]) and r[1] >= 262 and r[3] <= 700


def test_headline_left_out_when_nothing_fits():
    faces = [(0, 5, [80, 192, 592, 832])]
    entry, note = ag.place_headline("No Phone", 1, 3, faces, [], [], rect_fn)
    assert entry is None and "left out" in note


def test_headline_avoids_a_placed_sticker():
    taken = [(8.0, 11.0, (80, 192, 592, 400))]
    entry, _ = ag.place_headline("No Phone", 8.5, 10.4, [], [], [], rect_fn, taken)
    assert entry["y"] >= 400


def test_knit_read_as_a_face_gives_no_beside_face_spot():
    busy = np.ones((ag.H // ag.S, ag.W // ag.S), np.uint8)
    assert not ag.plausible_face([300, 992, 460, 1157])
    assert ag.fit_image(busy, [300, 992, 460, 1157], 1.0, [ag.RAIL]) is None


def test_cut_out_stays_off_the_product_on_screen():
    busy = np.ones((ag.H // ag.S, ag.W // ag.S), np.uint8)
    free = ag.fit_image(busy, FACE, 1.0, [ag.RAIL])
    r = ag.image_rect(free[1], free[2], free[0], 1.0)
    prod = [int(r[0]), int(r[1]), int(r[2]), int(r[3])]           # the product sits exactly there
    again = ag.fit_image(busy, FACE, 1.0, [ag.RAIL, prod])
    assert again is None or not ag.overlap(ag.image_rect(again[1], again[2], again[0], 1.0), prod)


def _gl():
    spec = importlib.util.spec_from_file_location("graphics_layer", os.path.join(HERE, "graphics_layer.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_cta_handed_over_by_post_must_be_in_the_plan():
    gl = _gl()
    report = {"pills": [], "subs": [], "headlines": [{"text": "Link below!", "start": 7.6, "end": 9.8}]}
    probs = list(gl.layout_check({"headlines": []}, report, gl.FONTS))
    assert any("handed 'Link below!'" in p for p in probs)
    plan = {"headlines": [{"text": "Link below!", "start": 7.6, "end": 9.8, "y": 400, "style": "pop", "size": 52}]}
    assert not any("handed" in p for p in gl.layout_check(plan, report, gl.FONTS))


def test_headline_avoids_the_held_product_and_a_moved_sub():
    """decker-cordless-drill 2026-11-27: '2 BATTERIES' went across the drill in his hand."""
    held = [(5.0, 7.0, (60, 192, 660, 520))]
    entry, _ = ag.place_headline("2 BATTERIES", 5.1, 6.4, [], [], [], rect_fn, (), held)
    assert entry["y"] >= 520
    subs, moved = [[5.0, 6.5, "s"]], [[60, 520, 580, 650]]          # the sub sits higher than the band
    entry, _ = ag.place_headline("2 BATTERIES", 5.1, 6.4, [], [], subs, rect_fn, (), held, moved)
    r = rect_fn("2 BATTERIES", entry["size"], entry["y"])
    assert not ag.overlap(r, moved[0]) and not ag.overlap(r, held[0][2])


def test_the_cut_out_stays_off_a_sub_moved_up_off_the_product():
    free = np.zeros((ag.H // ag.S, ag.W // ag.S), np.uint8)
    wins = [{"t0": 0.0, "t1": 2.6, "face": None, "busy": free}]
    assert ag.place_product_sticker(wins, "ref.jpg", 1.0, 0.0, 2.6)[0]
    sub = [(0.5, 2.0, (0, 262, ag.W, 700))]                      # a sub between chin and product filling the zone
    assert ag.place_product_sticker(wins, "ref.jpg", 1.0, 0.0, 2.6, None, sub)[0] is None


def _hsv_frame(w, h, bg=(0, 0, 200)):
    import cv2
    hsv = np.zeros((h, w, 3), np.uint8); hsv[:] = bg
    return hsv, lambda img: cv2.cvtColor(img, cv2.COLOR_HSV2BGR)


def test_hue_box_finds_a_muted_product_and_all_its_parts():
    import pytest
    pytest.importorskip("cv2")
    ref, bgr = _hsv_frame(300, 400)
    ref[60:340, 60:240] = (97, 190, 200)                      # the ad's vivid teal drill
    md = ag.hue_model(bgr(ref))
    assert md["hue"] in range(94, 101) and md["sat"] == ag.HUE_SAT
    frame, bgr = _hsv_frame(ag.W, ag.H, (20, 40, 170))        # beige room
    frame[150:420, 250:470] = (10, 120, 200)                  # skin
    frame[400:560, 100:260] = (97, 85, 110)                   # the drill on video: muted, darker
    frame[640:700, 130:250] = (97, 85, 110)                   # its battery accent, held lower
    box = ag.product_box(bgr(frame), md)
    assert box[0] <= 100 and box[1] <= 400 and box[2] >= 260 and box[3] >= 700
    assert box[2] < 470                                        # the face is not part of it


def test_a_skin_like_product_hue_does_not_match_an_orange_vest():
    import pytest
    pytest.importorskip("cv2")
    ref, bgr = _hsv_frame(300, 400)
    ref[60:340, 60:240] = (2, 220, 200)                       # red handle
    md = ag.hue_model(bgr(ref))
    assert md["tol"] == ag.HUE_TOL_SKIN and md["sat"] == ag.HUE_SAT_SKIN
    frame, bgr = _hsv_frame(ag.W, ag.H)
    frame[500:1000, 150:570] = (14, 230, 240)                 # hi-vis orange vest
    assert ag.product_box(bgr(frame), md) is None
    frame[300:600, 60:120] = (2, 220, 200)                    # the red handle in his hand
    box = ag.product_box(bgr(frame), md)
    assert box and box[2] < 200


def test_a_black_product_has_no_hue_model():
    import pytest
    pytest.importorskip("cv2")
    ref, bgr = _hsv_frame(300, 400)
    ref[60:340, 60:240] = (0, 0, 30)                          # black screwdriver
    ref[100:110, 100:110] = (12, 220, 230)                    # a tiny orange button
    assert ag.hue_model(bgr(ref)) is None
