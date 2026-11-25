import pillclear as pc

# venita-sunscreen shot 2 as measured (0.5 s apart there; doubled here to the module's 0.25 s step)
VENITA2 = [v / 100 for v in (38, 32, 22, 92, 93, 93, 93, 93, 83, 90, 69, 74, 80, 81, 55, 46, 57, 47, 44, 47) for _ in (0, 1)]
DETTOL1 = [v / 100 for v in (49, 50, 48, 42, 24, 14, 33, 51, 48, 49, 40, 50, 49, 49, 44, 51, 50, 51, 48, 47) for _ in (0, 1)]


def test_pill_over_hair_stays():
    assert pc.place(DETTOL1, 1.0, 3.5, 0.1, 9.5) == (1.0, 3.5)


def test_close_up_moves_the_pill_to_the_nearest_clear_window():
    assert pc.on_face(VENITA2, 1.0, 3.5)
    t0, t1 = pc.place(VENITA2, 1.0, 3.5, 0.1, 9.7)
    assert not pc.on_face(VENITA2, t0, t1)
    assert t1 - t0 >= pc.MIN_DUR


def test_close_up_that_lasts_until_the_cta_drops_the_pill():
    # the only clear stretch after the close-up is the CTA's own span, and 1.4 s before it is too short
    assert pc.place(VENITA2, 1.0, 3.5, 0.1, 9.7, taken=[(7.3, 9.5)]) is None


def test_moved_pill_keeps_its_gap_to_another_pill():
    t0, t1 = pc.place(VENITA2, 1.0, 3.5, 0.1, 9.7, taken=[(9.2, 9.7)])
    assert t1 + pc.GAP <= 9.2 and not pc.on_face(VENITA2, t0, t1)


def test_no_clear_window_drops_the_pill():
    assert pc.place([0.9] * 40, 1.0, 3.5, 0.1, 9.7) is None


def test_pill_width_tracks_the_text():
    assert pc.pill_width("NEW") < pc.pill_width("GEL TEXTURE") <= 560


# ---- sideways slot (yuedpao-rushbag 2026-11-25: full-body, ~140 px face, pills on her forehead)
# Fredoka-SemiBold box widths measured with PIL (advance + 34)
LINK = {40: 236, 38: 226, 36: 215, 34: 203, 32: 190, 30: 183}
YUED = [301, 202, 441, 342]          # Haar face box at 9.5 s


def test_head_box_pads_for_hair_and_drops_a_stray_box():
    head = pc.head_box([YUED, None, [305, 198, 444, 337], [320, 382, 451, 513]])   # last = her neck/shirt
    assert head[1] < 202 - 0.4 * 140 and head[0] < 301 - 20 and head[2] > 444 + 20
    assert head[3] < 382                     # the stray low box is not part of her head
    assert pc.head_box([None, None]) is None


def test_no_face_or_a_low_face_keeps_the_centred_pill():
    assert pc.slot(None, LINK.get) == (None, 40)
    assert pc.slot([280, 300, 440, 520], LINK.get) == (None, 40)    # head starts under the band


def test_full_body_face_moves_the_pill_beside_her_head():
    head = pc.head_box([YUED] * 8)
    x, font = pc.slot(head, LINK.get)
    assert font >= 30 and pc.X_MIN <= x and x + LINK[font] <= head[0] - pc.SLOT_GAP


def test_the_side_with_more_room_wins():
    x, font = pc.slot([60, 150, 380, 400], LINK.get)       # head pushed left: only the right side has room
    assert x >= 390 and x + LINK[font] <= pc.X_MAX


def test_close_up_has_no_side_room():
    assert pc.slot([90, 120, 640, 760], LINK.get) is None


def test_relocate_moves_to_the_nearest_window_with_a_slot():
    fit = lambda a, b: (100, 36) if a >= 5.0 else None
    assert pc.relocate(fit, 1.0, 3.0, 0.1, 9.5) == (5.1, 7.1, (100, 36))    # grid from lo = 0.1 in 0.25 s steps
    assert pc.relocate(lambda a, b: None, 1.0, 3.0, 0.1, 9.5) is None


def test_window_indexes_like_on_face():
    s = list(range(40))
    assert pc.window(s, 1.0, 2.0) == s[4:9]


def test_width_fn_falls_back_without_the_font():
    w = pc.width_fn("/nonexistent/font.ttf")
    assert w("NEW", 32) < w("NEW", 40) == pc.pill_width("NEW")
