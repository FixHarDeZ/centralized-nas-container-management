"""subclear.py: where a burned subtitle goes when the product she holds sits in the sub band."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subclear as sc

W2, H2 = sc.size([288, 200])                     # a 2-line sub: 300 x 128


def test_no_product_or_a_product_clear_of_the_band_keeps_the_sub():
    assert sc.choose(W2, H2, None, None)["how"] == "kept"
    assert sc.choose(W2, H2, [60, 300, 300, 600], [250, 100, 470, 450])["how"] == "kept"      # held at the cheek
    assert sc.size([288, 200]) == (300, 128)


def test_a_drill_at_chest_height_pushes_the_sub_aside():
    """decker-cordless-drill 2026-11-27 7.2 s: the drill and its battery at x 13-398, y 521-989."""
    prod, face = [13, 521, 398, 989], [250, 100, 470, 450]
    ch = sc.choose(W2, H2, prod, face)
    assert ch["how"] == "moved" and ch["cover0"] > sc.COVER_MAX and ch["cover"] <= ch["cover0"] / 2
    r = ch["rect"]
    assert r[0] >= sc.X_LO and r[2] <= sc.X_HI and r[3] <= sc.Y_BOT and sc.inter(r, face) == 0
    ml, mr, mv = sc.margins(ch, W2)
    assert abs((ml + (sc.W - mr)) / 2 - ch["cx"]) <= 1 and mv == sc.H - ch["yb"]


def test_a_product_filling_the_chest_with_the_face_above_is_stuck():
    ch = sc.choose(W2, H2, [60, 450, 660, 900], [200, 100, 520, 440])
    assert ch["how"] == "stuck" and ch["rect"] == sc.rect(320, 815, W2, H2)


def test_a_one_line_sub_on_a_big_product_box_moves_and_the_worst_moment_counts():
    """decker 5.0-5.7 'แบตสองก้อน' sat on the battery: 7 % of the padded box, 77 % of the sub."""
    w, h = sc.size([250])
    face = [167, 49, 563, 471]
    ch = sc.choose(w, h, [[0, 442, 391, 951], None], face)
    assert ch["cover0"] > 0.7 and ch["how"] == "moved" and ch["cover"] <= ch["cover0"] / 2
    assert sc.choose(w, h, [[400, 300, 700, 500], [0, 600, 400, 900]], face)["cover0"] > 0.5     # 2nd moment counts


def test_an_insert_close_up_moment_is_left_out():
    """decker 2.15 s: the drill fills the frame (box 17-464 x 159-1147); no spot can miss it, the other moments decide."""
    w, h = sc.size([300, 180])
    face = [193, 44, 540, 440]
    ch = sc.choose(w, h, [[41, 397, 297, 800], [17, 159, 464, 1147]], face)
    assert ch["how"] == "moved" and ch["cover"] <= sc.COVER_MAX and ch["rect"][0] >= 260
    assert sc.choose(w, h, [[17, 159, 464, 1147]], None)["how"] == "kept"


def test_with_no_head_measured_the_sub_never_climbs():
    prod = [60, 600, 660, 840]                                   # only clear spot is higher up
    assert sc.choose(W2, H2, prod, None)["how"] == "stuck"
    ch = sc.choose(W2, H2, prod, [250, 60, 470, 300])
    assert ch["how"] == "moved" and ch["cover"] <= sc.COVER_MAX and ch["yb"] <= 610 and ch["rect"][1] >= 312
