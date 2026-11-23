"""sub_linecheck verdict: a 2-line Thai event whose marks bridge the rows still passes on its line bodies."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "sub_linecheck", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sub_linecheck.py"))
slc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slc)


def rows(*spans):
    """(y0, y1, n_lit) spans -> lit rows (contiguous rows inside each span)."""
    out = []
    for y0, y1, n in spans:
        out += [(y, n, 200, 200 + n) for y in range(y0, y1 + 1)]
    return sorted(out)


# ps5-discdrive event 3 (2026-11-23): one lit band 722-816, bodies 738-756 / 787-804
BRIDGED = rows((722, 737, 8), (738, 756, 200), (757, 786, 10), (787, 804, 180), (805, 816, 8))


def test_bridged_two_lines_pass():
    ok, note = slc.verdict(BRIDGED, 2)
    assert ok and "bridge" in note and "31px" in note


def test_two_real_bands_pass_without_note():
    assert slc.verdict(rows((728, 756, 150), (766, 804, 160)), 2) == (True, "")


def test_one_body_for_two_lines_fails():
    # the second line was lost (cut/one long line): one band, one dense body
    assert slc.verdict(rows((722, 737, 8), (738, 760, 200), (761, 770, 8)), 2)[0] is False


def test_bodies_too_close_fail():
    ok, note = slc.verdict(rows((738, 756, 200), (757, 763, 10), (764, 780, 190)), 2)
    assert not ok and "apart" in note


def test_extra_band_still_fails():
    # a long line wrapped into 2 bands where 1 was wanted
    assert slc.verdict(rows((728, 756, 150), (766, 804, 160)), 1)[0] is False


def test_gap_sample_empty():
    assert slc.verdict([], 0) == (True, "")
    assert slc.verdict(rows((766, 804, 160)), 0)[0] is False
