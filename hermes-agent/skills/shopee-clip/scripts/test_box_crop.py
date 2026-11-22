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
