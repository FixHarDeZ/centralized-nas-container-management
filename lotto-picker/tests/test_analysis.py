import json
import random
from pathlib import Path

from app import analysis, lotto

FIX = Path(__file__).parent / "fixtures"
PRIZES = lotto.parse_prizes(json.loads((FIX / "latest_2026-10-01.json").read_text())["response"]["data"])


def fake_draws(n, seed=1):
    """n complete-looking draws, newest first, with uniformly random numbers."""
    rng = random.Random(seed)

    def six():
        return f"{rng.randrange(1_000_000):06d}"

    out = []
    for i in range(n):
        prizes = {k: [six() for _ in range(c)] for k, c in lotto.EXPECTED_COUNTS.items()}
        prizes["last3f"] = [f"{rng.randrange(1000):03d}" for _ in range(2)]
        prizes["last3b"] = [f"{rng.randrange(1000):03d}" for _ in range(2)]
        prizes["last2"] = [f"{rng.randrange(100):02d}"]
        out.append({"date": f"20{10 + i // 24:02d}-{1 + (i // 2) % 12:02d}-{1 if i % 2 else 16:02d}",
                    "prizes": prizes})
    return sorted(out, key=lambda d: d["date"], reverse=True)


def test_categories_skip_near1_and_take_last_digits():
    nums = analysis.category_numbers(PRIZES, 3, "all")
    assert len(nums) == 1 + 5 + 10 + 50 + 100 + 2 + 2  # no near1
    assert analysis.category_numbers(PRIZES, 3, "targets") == [
        PRIZES["first"][0][-3:], *PRIZES["last3f"], *PRIZES["last3b"]
    ]
    assert analysis.category_numbers(PRIZES, 2, "last2") == PRIZES["last2"]


def test_counts_gaps_and_last_seen_newest_first():
    draws = [
        {"date": "2026-03-01", "prizes": {"last2": ["11"]}},
        {"date": "2026-02-16", "prizes": {"last2": ["22"]}},
        {"date": "2026-02-01", "prizes": {"last2": ["11"]}},
    ]
    counts, gaps, last = analysis.counts_and_gaps(draws, 2, "last2")
    assert counts["11"] == 2 and gaps["11"] == 0 and last["11"] == "2026-03-01"
    assert counts["22"] == 1 and gaps["22"] == 1
    assert counts["33"] == 0 and gaps["33"] == 3 and last["33"] is None


def test_chance_profile_band_and_extremes_are_sane():
    c = analysis.chance_profile(480, 0.01, 100)
    assert c["expected"] == 4.8
    lo, hi = c["band"]
    assert lo <= 2 and 8 <= hi <= 10
    # with 100 numbers the largest count is usually around 10, not 4.8
    assert 9 <= c["max_typical"][0] <= 11
    assert c["min_typical"][1] <= 1
    assert 2 <= c["outside_expected"] <= 8


def test_frequency_on_random_draws_mostly_inside_band():
    draws = fake_draws(240)
    f = analysis.frequency(draws, 2, "last2")
    assert f["draws"] == 240 and sum(r["count"] for r in f["numbers"]) <= 240
    assert len(f["numbers"]) == 100
    assert f["max_seen"] <= f["max_typical"][1] + 2
    f3 = analysis.frequency(draws, 3, "all")
    assert len(f3["numbers"]) == 1000
    assert abs(f3["expected"] - 240 * (1 - (1 - 1 / 1000) ** 170)) < 0.5


def test_style_candidates_keep_ties_and_quarter():
    pool = [f"{i:02d}" for i in range(100)]
    counts = {n: (3 if n < "10" else 1) for n in pool}
    gaps = {n: int(n) for n in pool}
    hot = analysis.style_candidates(pool, counts, gaps, "hot", 5)
    assert hot == pool[:10] + pool[10:]  # the cut lands inside the tie → ties kept
    counts = {n: int(n) for n in pool}
    assert analysis.style_candidates(pool, counts, gaps, "hot", 5) == pool[75:]
    assert analysis.style_candidates(pool, counts, gaps, "cold", 5) == pool[:25]
    assert analysis.style_candidates(pool, counts, gaps, "overdue", 30) == pool[70:]
    assert analysis.style_candidates(pool, counts, gaps, "random", 5) == pool


def test_backtest_uses_only_past_and_matches_baseline_expectation():
    draws = fake_draws(80)
    bt = analysis.backtest(draws, 2, picks=5, exclude_draws=2, scope="last2", permute=False)
    assert bt["plays"] == 80 - 24
    names = [r["strategy"] for r in bt["strategies"]]
    assert names == ["baseline", "random", "hot", "cold", "overdue"]
    base = bt["strategies"][0]
    assert base["numbers"] == 5 * bt["plays"]
    assert abs(base["hits"] - base["expected"]) < 1e-6  # baseline is the expectation itself
    assert len(bt["series"]["dates"]) == bt["plays"]


def alternating(n):
    draws = [{"date": f"2020-{1 + i // 2:02d}-{1 if i % 2 == 0 else 16:02d}",
              "prizes": {"last2": ["07" if i % 2 else "08"]}} for i in range(n)]
    return sorted(draws, key=lambda d: d["date"], reverse=True)


def test_backtest_hot_style_learns_from_the_past(monkeypatch):
    # top-1 instead of top quarter: with "07"/"08" alternating and the last draw
    # excluded, hot holds exactly the other number — which is the next draw.
    monkeypatch.setattr(analysis, "STYLE_SHARE", 0)
    bt = analysis.backtest(alternating(40), 2, picks=1, exclude_draws=1, scope="last2",
                           permute=False, min_history=4)
    hot = next(r for r in bt["strategies"] if r["strategy"] == "hot")
    assert hot["hits"] == bt["plays"] and hot["significant"]


def test_backtest_never_reads_the_draw_it_scores():
    draws = fake_draws(40)
    before = analysis.backtest(draws, 2, 5, 2, "last2", False)
    changed = [dict(draws[0], prizes={**draws[0]["prizes"], "last2": ["99"]}), *draws[1:]]
    after = analysis.backtest(changed, 2, 5, 2, "last2", False)
    for s in ("random", "hot", "cold", "overdue"):
        assert before["series"][s][:-1] == after["series"][s][:-1]


def test_backtest_flags_a_moderate_real_bias():
    # "07" drawn 15% of the time instead of 1%. Hot keeps it in its quarter and
    # beats chance clearly: z ≈ 3.8 with the right null variance, while the
    # realised-count variance k*p*(1-p) reports z ≈ 1.1 — "not significant".
    rng = random.Random(3)
    draws = [{"date": f"{2000 + i // 24}-{1 + (i // 2) % 12:02d}-{1 if i % 2 == 0 else 16:02d}",
              "prizes": {"last2": ["07" if rng.random() < 0.15 else f"{rng.randrange(100):02d}"]}}
             for i in range(400)]
    draws.sort(key=lambda d: d["date"], reverse=True)
    bt = analysis.backtest(draws, 2, picks=5, exclude_draws=1, scope="last2", permute=False)
    hot = next(r for r in bt["strategies"] if r["strategy"] == "hot")
    assert hot["significant"] and hot["z"] > 3
    random_row = next(r for r in bt["strategies"] if r["strategy"] == "random")
    assert not random_row["significant"]


def test_ticket_prizes_sum_overlapping_wins():
    first = PRIZES["first"][0]
    won = lotto.ticket_prizes(first, PRIZES)
    assert "first" in won
    value = lotto.ticket_value(first, PRIZES, {})
    assert value >= 6_000_000
    assert lotto.ticket_prizes("000000", {"last2": ["00"]}) == ["last2"]
    assert lotto.ticket_value("123456", {"last3f": ["123"], "last2": ["56"]}, {}) == 6000


def test_expected_return_is_sixty_percent_from_the_table():
    assert round(lotto.expected_return({}), 4) == 0.6
