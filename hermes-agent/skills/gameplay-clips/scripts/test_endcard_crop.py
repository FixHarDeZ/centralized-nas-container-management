"""endcard_crop: title vs. legal / platform / badge boxes, the crop plan and the card run (no OCR run here).
Numbers from switch2-oblivion-rd's trailer card at 102.16 s (1920x1080), 2026-11-22."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import endcard_crop as ec  # noqa: E402


def box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


CARD = [(box(765, 95, 1155, 145), "The Gjlder Scrolls IV", 0.9), (box(585, 190, 1345, 300), "OBLIVION", 0.95),
        (box(810, 375, 1110, 410), "REMASTERED", 0.9), (box(760, 520, 1160, 578), "OUT NOW", 0.9),
        (box(870, 680, 1050, 770), "B2", 0.7), (box(880, 790, 1045, 808), "NINTENDO", 0.8),
        (box(878, 812, 1050, 842), "SWITCH..", 0.8), (box(72, 952, 258, 985), '"Bethesda', 0.9),
        (box(1652, 948, 1850, 985), "BETHESDA", 0.9),
        (box(785, 1015, 1135, 1030), "2026ZENIMAXMEDIAINC.ALLRIGHTSRESERVED.", 0.8),
        (box(712, 1045, 1210, 1068), "Nintendo Switch is a trademark of Nintendo.", 0.8)]


def test_classify_keeps_the_title_only():
    kept, dropped = ec.classify(CARD, 1920, 1080)
    assert [k["text"] for k in kept] == ["The Gjlder Scrolls IV", "OBLIVION", "REMASTERED", "OUT NOW"]
    why = {d["text"]: d["why"] for d in dropped}
    assert why["B2"] == "badge" and why["NINTENDO"] == "words" and why['"Bethesda'] == "corner"
    assert why["2026ZENIMAXMEDIAINC.ALLRIGHTSRESERVED."] == "words"


def test_plan_crop_has_margin_fits_the_window_and_shows_no_dropped_box():
    kept, dropped = ec.classify(CARD, 1920, 1080)
    crop, problem = ec.plan_crop(kept, dropped, 1920, 1080, 720)
    assert problem is None
    x, y, w, h = crop
    assert w * 720 >= h * 720                                  # at least as wide as the 1:1 window
    assert x <= 585 - 12 and x + w >= 1345 + 12 and y <= 95 - 12 and y + h >= 578 + 12
    for d in dropped:
        r = d["rect"]
        assert not (r[0] < x + w and x < r[2] and r[1] < y + h and y < r[3]), d["text"]
    # 16:9 band window: the crop widens to 16:9 (it may run to the frame width)
    crop, _ = ec.plan_crop(kept, dropped, 1920, 1080, 405)
    assert crop[2] * 405 >= crop[3] * 720 - 720


def test_plan_crop_refuses_a_platform_line_inside_the_title_block():
    kept = [{"text": "MARIO", "rect": [600, 100, 1300, 300]}, {"text": "KART", "rect": [600, 500, 1300, 700]}]
    dropped = [{"text": "Nintendo Switch", "rect": [700, 380, 1200, 420], "why": "words"}]
    crop, problem = ec.plan_crop(kept, dropped, 1920, 1080, 720)
    assert crop is None and "inside the title block" in problem


def test_card_run_is_the_longest_title_run_and_the_core_is_fully_up():
    k = lambda n: [{"text": "x" * n, "rect": [0, 0, 1, 1]}]          # noqa: E731
    samples = [(89.2, k(10)), (89.7, k(10)), (90.2, []), (99.7, k(27)), (100.2, k(28)), (100.7, k(39)),
               (101.2, k(41)), (101.7, k(44)), (102.2, k(44)), (102.7, k(45)), (103.2, k(45)), (103.7, k(42))]
    assert ec.card_run(samples) == (99.7, 103.7)
    assert ec.card_run(samples, ec.CORE_SHARE) == (101.2, 103.7)
    assert ec.card_run([(1.0, []), (1.5, [])]) is None
