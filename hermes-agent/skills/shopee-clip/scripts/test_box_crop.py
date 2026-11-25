"""box_crop: side extension to a full edge line + de-duplication (no OpenCV contours here)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import box_crop as bc  # noqa: E402


def steps(h, w, rows=(), cols=(), span=None):
    """Synthetic Lab step maps: full-width row edges at `rows`, full-height col edges at `cols`."""
    gy = np.zeros((h - 1, w), np.float32)
    gx = np.zeros((h, w - 1), np.float32)
    for r in rows:
        gy[r, :] = 100.0
    for c in cols:
        gx[:, c] = 100.0
    if span:                                     # a partial line (a background wave): only part of the width
        r, x0, x1 = span
        gy[r, x0:x1] = 100.0
    return gy, gx


def test_extend_reaches_the_case_header_but_not_a_partial_wave():
    """oblivion listing: art box 162-762, the red header's top edge at 57, a wave crossing 69 % of the span at 803."""
    gy, gx = steps(950, 950, rows=(57,), span=(803, 143, 430))
    assert bc.extend((143, 162, 420, 600), gy, gx, 950, 950) == (143, 57, 420, 705)


def test_dedupe_keeps_the_bigger_of_near_identical_rects():
    a, b, c = (141, 56, 422, 706), (143, 57, 420, 705), (143, 162, 420, 600)
    assert bc.dedupe([b, a, c]) == [a, c]
    assert bc.iou(a, a) == 1.0 and bc.iou(a, (900, 900, 10, 10)) == 0.0


def page(h=400, w=400, fill=255.0):
    return np.full((h, w), fill, np.float32)


def test_split_runs_cuts_only_at_long_gutters_and_trims_the_ends():
    f = np.array([1, 1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 1, 1, 0, 0, 1], bool)
    # leading/trailing gutters trimmed, the 1-line gutter at 5 is content, the 5-line one at 8-12 cuts
    assert bc.split_runs(f) == [(2, 8), (13, 15)]
    assert bc.split_runs(np.ones(8, bool)) == []


def test_panels_photo_above_a_strip_of_three_steps():
    """ps2-hdd-175 img2 in miniature: a busy photo on top, three step tiles below, white gutters."""
    g = page()
    rng = np.random.default_rng(0)
    g[0:240, 0:330] = rng.uniform(0, 255, (240, 330))            # the photo (no gutter inside)
    for x0 in (4, 136, 268):                                     # three grey step tiles with an object each
        g[270:396, x0:x0 + 128] = 238.0
        g[300:360, x0 + 20:x0 + 100] = rng.uniform(0, 120, (60, 80))   # a small textured object
    rects = bc.panels(g)
    assert rects[0][:2] == (0, 0) and rects[0][3] == 240 + bc.MARGIN
    assert 330 <= rects[0][0] + rects[0][2] <= 342                  # trimmed right margin, MARGIN kept
    assert len(rects) == 4
    steps = rects[1:]
    assert [r[0] for r in steps] == sorted(r[0] for r in steps)       # the steps read left to right
    assert all(r[2] >= 100 and r[3] >= 120 for r in steps)            # whole tiles, not the small objects


def test_panels_offers_nothing_for_one_photo():
    rng = np.random.default_rng(1)
    assert bc.panels(rng.uniform(0, 255, (300, 300)).astype(np.float32)) == []


def test_extend_ignores_the_screenshot_border_line():
    """cal-d-protein-1mo 2026-11-25: a 1-px grey border at y 0 and y 950 was the 'farthest full edge line', so every
    candidate ran the full image height (box + x2 badge + OFFICIAL STORE banner) and Hermes probed pixels for 3 h."""
    gy, gx = steps(951, 950, rows=(0, 802, 949))
    assert bc.extend((149, 226, 303, 484), gy, gx, 950, 951) == (149, 226, 303, 577)


def badge_listing():
    """Two lavender boxes with a navy bottom band on white, a red 'x2' disc on each top-right corner."""
    import pytest
    cv2 = pytest.importorskip("cv2")
    img = np.full((951, 950, 3), 255, np.uint8)
    img[0, :] = img[950, :] = 129
    for x0 in (149, 504):
        img[226:803, x0:x0 + 303] = (230, 200, 215)          # BGR lavender face
        img[710:803, x0:x0 + 303] = (110, 40, 30)            # navy band
        cv2.circle(img, (x0 + 290, 230), 45, (40, 20, 150), -1)
        cv2.putText(img, "x2", (x0 + 268, 245), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
        cv2.circle(img, (x0 + 60, 640), 34, (20, 120, 240), -1)   # printed "20g" disc on the face: never painted
    return img


def test_badge_on_the_box_corner_is_reported_and_can_be_painted(tmp_path):
    import pytest
    cv2 = pytest.importorskip("cv2")
    p = str(tmp_path / "img1.jpg")
    cv2.imwrite(p, badge_listing())
    assert bc.main([p, "--out-dir", str(tmp_path), "--n", "6"]) == 0
    res = __import__("json").loads((tmp_path / "box_crop.json").read_text())
    rects = [c["rect"] for c in res["candidates"]]
    assert any(abs(r[1] - 226) <= 4 and abs(r[1] + r[3] - 803) <= 4 for r in rects), rects   # the box, not full height
    assert all(r[3] < 900 for r in rects)
    box = next(c for c in res["candidates"] if abs(c["rect"][1] - 226) <= 4)
    assert box["badges"] and not box.get("painted")
    assert bc.main([p, "--out-dir", str(tmp_path), "--n", "6", "--paint-badge"]) == 0
    res = __import__("json").loads((tmp_path / "box_crop.json").read_text())
    box = next(c for c in res["candidates"] if abs(c["rect"][1] - 226) <= 4)
    assert box["painted"]
    crop = cv2.imread(box["file"])
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 1] > 110) & ((hsv[..., 0] < 10) | (hsv[..., 0] > 170))).mean()
    assert red < 0.002, red
    ox, oy = box["rect"][:2]
    assert hsv[640 - oy, 60 + 149 - ox][1] > 150                   # the printed disc is still there
