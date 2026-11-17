"""Where to cut a whole-script Gemini take into phrases.

Why (2026-11-17, dragonddogma2-sw2-gameplay): the old cut = quietest 20 ms within +-0.35 s of a
character-proportion estimate. The estimate ran 0.3-0.5 s late, so the real line pause (0.42-0.65 s)
fell outside the window and the cut snapped to the 60 ms closure of a stop consonant INSIDE a word
("ดรา|ก้อน", "โลก|เปิด"). gen_vo_natural then put `gap_after` there = a 0.5 s hole mid-word.

Gemini pauses at every newline of the script, and those pauses are the longest silences in the take.
So the cuts are chosen from real pauses: an ordered set of N-1 pauses that maximises
sum(pause length) - SLOPE * sum(|pause middle - estimate|). Cut = middle of the pause.
"""
import numpy as np

FRAME = 0.01        # s per envelope frame
REL_DB = -24.0      # a frame is quiet when it is this far below the take's p95 loudness
MIN_RUN = 0.06      # s; shorter quiet runs are ignored
REACH = 1.5         # s; a pause further than this from its estimate is never used for it
SLOPE = 0.3         # s of pause length worth giving up per s of distance from the estimate
REAL_PAUSE = 0.15   # s; a cut in a shorter run is likely inside a word -> warn


def pauses(mono, sr):
    """Quiet runs of a mono float/int take -> [(start_s, end_s)]."""
    win = int(FRAME * sr)
    n = len(mono) // win
    if n == 0:
        return []
    x = np.asarray(mono[:n * win], np.float64).reshape(n, win)
    db = 20 * np.log10(np.sqrt((x ** 2).mean(1)) + 1e-9)
    quiet = db < np.percentile(db, 95) + REL_DB
    runs, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) * FRAME >= MIN_RUN:
                runs.append((i * FRAME, j * FRAME))
            i = j
        else:
            i += 1
    total = n * FRAME
    # leading/trailing silence is not a phrase boundary
    return [(a, b) for a, b in runs if a > 0.05 and b < total - 0.05]


def pick(runs, estimates):
    """Choose one run per estimate, in order, no run used twice.
    -> list of (cut_s, run_len_s) or None when there are fewer usable runs than estimates."""
    k, m = len(estimates), len(runs)
    if k == 0:
        return []
    if m < k:
        return None
    mid = [(a + b) / 2 for a, b in runs]
    ln = [b - a for a, b in runs]
    NEG = -1e18

    def score(i, j):
        d = abs(mid[j] - estimates[i])
        return NEG if d > REACH else ln[j] - SLOPE * d

    best = [[NEG] * m for _ in range(k)]
    back = [[-1] * m for _ in range(k)]
    for j in range(m):
        best[0][j] = score(0, j)
    for i in range(1, k):
        run_max, run_arg = NEG, -1
        for j in range(m):
            if j - 1 >= 0 and best[i - 1][j - 1] > run_max:
                run_max, run_arg = best[i - 1][j - 1], j - 1
            s = score(i, j)
            if run_max > NEG / 2 and s > NEG / 2:
                best[i][j] = run_max + s
                back[i][j] = run_arg
    j = max(range(m), key=lambda c: best[k - 1][c])
    if best[k - 1][j] <= NEG / 2:
        return None
    out = []
    for i in range(k - 1, -1, -1):
        out.append((mid[j], ln[j]))
        j = back[i][j]
    return out[::-1]
