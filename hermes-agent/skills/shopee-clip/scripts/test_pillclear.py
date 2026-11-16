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
