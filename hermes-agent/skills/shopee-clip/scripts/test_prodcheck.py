"""prodcheck: the change rule on band series (no OpenCV here)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prodcheck as pc  # noqa: E402


def series(vals, band=5, step=0.5):
    return [(round(i * step, 2), {band: v, 0: 1.0, 1: 1.0}) for i, v in enumerate(vals)]


def test_a_band_that_changes_and_stays_is_flagged():
    """cal-d-protein-1mo 2026-11-25: the bottom band held ΔE 34-36 from 3 s."""
    s = series([0, 1, 2, 2, 1, 2, 35, 36, 34, 35, 36, 35])
    f = pc.find_changes(s, 0.5)
    assert f == [{"band": "bottom", "from": 3.0, "to": 5.5, "de": 36}]
    assert pc.sustained_peak(s, 0.5) == 35            # best 1 s window: 35, 36, 35


def test_a_one_frame_spike_is_not_a_change():
    s = series([0, 2, 40, 2, 3, 30, 2, 1])            # a hand / glare for one sample
    assert pc.find_changes(s, 0.5) == [] and pc.sustained_peak(s, 0.5) < pc.DE_CHANGE


def test_clean_shot_levels_stay_under_the_threshold():
    s = series([0, 3, 5.7, 4, 5, 2, 3, 4])            # the worst clean calibration shot held 5.7
    assert pc.find_changes(s, 0.5) == []


def test_band_shift_removes_the_frames_overall_shift():
    import numpy as np
    base = [np.array([50.0, 10, -10])] * 6
    cur = [b + np.array([5.0, 2, 2]) for b in base]   # the whole product a little brighter / warmer
    cur[5] = base[5] + np.array([-30.0, 20, 30])      # the bottom band turned brown
    d = pc.band_shift(base, cur)
    assert max(d[i] for i in range(5)) < 1 and d[5] > 40


def test_verdict():
    assert pc.verdict({"r": {"flags": [{"band": "bottom"}], "matched": 9}}) == "change"
    assert pc.verdict({"r": {"flags": [], "matched": 9}}) == "stable"
    assert pc.verdict({"r": {"flags": [], "matched": 0}}) == "no-match"
