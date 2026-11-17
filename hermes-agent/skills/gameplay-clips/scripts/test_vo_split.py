"""Unit tests for vo_split (where a whole Gemini take is cut into phrases)."""
import importlib.util
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vo_split", os.path.join(HERE, "vo_split.py"))
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

SR = 16000


def take(layout):
    """layout = [(seconds, loud?)] -> mono float take: noise for speech, near-silence for gaps."""
    rng = np.random.default_rng(0)
    parts = [rng.normal(0, 0.3 if loud else 0.0005, int(s * SR)) for s, loud in layout]
    return np.concatenate(parts)


def test_pauses_finds_runs_and_ignores_edges():
    x = take([(0.2, False), (1.0, True), (0.5, False), (1.0, True), (0.07, False), (1.0, True), (0.3, False)])
    runs = vs.pauses(x, SR)
    assert len(runs) == 2                     # lead/tail silence dropped
    (a0, b0), (a1, b1) = runs
    assert abs(a0 - 1.2) < 0.02 and abs(b0 - 1.7) < 0.02
    assert abs((b1 - a1) - 0.07) < 0.02       # a stop-consonant-sized dip is still a run


def test_dragonsdogma_case_prefers_real_pause_over_nearby_dip():
    # Measured 2026-11-17 on gemini_take2.wav: line pause 3.72-4.16, word-internal dip 4.37-4.43,
    # ASR estimate 4.64. The old +-0.35 s quietest-point snap took the dip (ดรา|ก้อน).
    runs = [(3.72, 4.16), (4.37, 4.43), (7.41, 7.93), (8.18, 8.25)]
    got = vs.pick(runs, [4.64, 8.42])
    assert [round(c, 2) for c, _ in got] == [3.94, 7.67]


def test_full_measured_take():
    runs = [(1.61, 1.77), (3.25, 3.36), (3.72, 4.16), (4.37, 4.43), (4.84, 4.92), (5.8, 5.91),
            (7.41, 7.93), (8.18, 8.25), (8.36, 8.48), (8.88, 9.11), (10.03, 10.34), (12.35, 12.93),
            (13.39, 13.45), (14.41, 14.54), (15.39, 15.68), (16.79, 17.44), (17.59, 17.67),
            (19.42, 19.84), (20.24, 20.3), (21.0, 21.18)]
    got = vs.pick(runs, [4.64, 8.42, 13.26, 17.5, 19.92])
    assert [round(c, 2) for c, _ in got] == [3.94, 7.67, 12.64, 17.12, 19.63]
    assert all(ln >= vs.REAL_PAUSE for _, ln in got)


def test_order_kept_and_no_run_reused():
    runs = [(1.0, 1.6), (2.0, 2.1)]
    got = vs.pick(runs, [1.2, 1.4])          # both estimates near the one big pause
    assert [round(c, 2) for c, _ in got] == [1.3, 2.05]


def test_far_pause_not_used_and_too_few_runs_is_none():
    assert vs.pick([(10.0, 10.6)], [2.0]) is None     # beyond REACH
    assert vs.pick([(1.0, 1.5)], [1.2, 3.0]) is None   # fewer runs than boundaries
    assert vs.pick([], []) == []
