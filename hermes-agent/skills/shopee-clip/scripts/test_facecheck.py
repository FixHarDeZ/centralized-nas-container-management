"""facecheck.skin_share: knit/phone boxes read ~0, a face reads high (measured 2026-11-19: 0.00-0.08 vs 0.82-0.98)."""
import importlib.util
import os

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("facecheck", os.path.join(HERE, "facecheck.py"))
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def box(bgr):
    return np.full((300, 300, 3), bgr, np.uint8)


def test_skin_reads_high_and_knit_or_screen_low():
    assert fc.skin_share(box((150, 175, 225)), 0, 0, 300, 300) > fc.SKIN_MIN     # warm skin tone (BGR)
    assert fc.skin_share(box((215, 230, 235)), 0, 0, 300, 300) < fc.SKIN_MIN     # cream knit
    assert fc.skin_share(box((90, 160, 40)), 0, 0, 300, 300) < fc.SKIN_MIN       # green phone screen


def test_blank_frame_has_no_face():
    box_, hits = fc.detect(box((128, 128, 128)))
    assert box_ is None and hits == []
