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


# Whisper "small" word tokens of the real ps2-hdd-175 Gemini take (2026-11-24), numbers split over tokens.
PS2_TAKE = [
    ("โ", 0.2, 0.4), ("อ", 0.4, 0.5), ("้", 0.5, 0.62), ("โ", 0.62, 0.62), ("ห", 0.62, 0.82),
    (" เด", 1.4, 1.5), ("ี", 1.5, 1.56), ("๋", 1.56, 1.58), ("ย", 1.58, 1.58), ("ว", 1.58, 1.6), ("น", 1.6, 1.66),
    ("ี้", 1.66, 1.74), ("เล", 1.74, 1.84), ("่", 1.84, 1.84), ("น", 1.84, 1.92), ("เก", 1.92, 2.0), ("ม", 2.0, 2.12),
    ("ได", 2.12, 2.24), ("้", 2.24, 2.32), ("ง", 2.32, 2.36), ("่", 2.36, 2.42), ("าย", 2.42, 2.74), ("ๆ", 2.74, 2.74),
    ("แ", 2.74, 2.84), ("บ", 2.84, 2.86), ("บ", 2.86, 2.98), ("น", 2.98, 3.0), ("ี้", 3.0, 3.1), ("เลย", 3.1, 3.3),
    (" เส", 3.6, 3.72), ("ี", 3.72, 3.82), ("ย", 3.82, 3.86), ("ป", 3.86, 3.98), ("ุ", 3.98, 4.04), ("๊", 4.04, 4.16),
    ("บ", 4.16, 4.16), ("เล", 4.16, 4.32), ("่", 4.32, 4.36), ("น", 4.36, 4.4), ("ได", 4.4, 4.46), ("้", 4.46, 4.54),
    ("เลย", 4.54, 4.68),
    ("เล", 5.04, 5.24), ("ื", 5.24, 5.3), ("อก", 5.3, 5.4), ("ได", 5.4, 5.52), ("้", 5.52, 5.8),
    (" 175", 5.8, 6.26), (" 22", 6.26, 7.2), ("5", 7.2, 7.84), (" 27", 7.84, 8.34), ("5", 8.34, 8.88),
    (" เก", 8.92, 9.02), ("ม", 9.02, 9.22),
    (" ล", 9.54, 9.66), ("ิ", 9.66, 9.68), ("่", 9.68, 9.68), ("ง", 9.68, 9.76), ("ใ", 9.76, 9.76), ("ต", 9.76, 9.84),
    ("้", 9.84, 9.94), ("ค", 9.94, 9.96), ("ล", 9.96, 10.02), ("ิ", 10.02, 10.06), ("ป", 10.06, 10.12),
    ("เลย", 10.12, 10.24),
]
PS2_SAY = ["โอ้โห เดี๋ยวนี้เล่นเกมได้ง่ายๆ แบบนี้เลย", "เสียบปุ๊บ เล่นได้เลย",
           "เลือกได้ หนึ่งร้อยเจ็ดสิบห้า สองร้อยยี่สิบห้า สองร้อยเจ็ดสิบห้า เกม", "ลิงก์ใต้คลิปเลย"]


def test_estimates_count_numbers_as_spoken():
    """The `say` line spells 175 in Thai words, Whisper writes digits: each estimate must still land within
    REACH of its real pause (3.30-3.60, 4.68-5.04, 9.22-9.54) so pick() can choose it. Counting raw characters
    put the first estimate in the opening words and the subtitle ended at 1.38 s."""
    est = vs.estimate_bounds(PS2_TAKE, PS2_SAY)
    for e, (a, b) in zip(est, [(3.30, 3.60), (4.68, 5.04), (9.22, 9.54)]):
        assert a - 0.5 <= e <= b + 0.5, est


def test_estimates_digit_say_lines_too():
    """A `say` written with digits counts the same as one written in words."""
    words = vs.estimate_bounds(PS2_TAKE, PS2_SAY)
    digits = vs.estimate_bounds(PS2_TAKE, [*PS2_SAY[:2], "เลือกได้ 175 225 275 เกม", PS2_SAY[3]])
    assert digits == words
