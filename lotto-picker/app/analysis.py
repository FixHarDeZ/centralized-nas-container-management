"""History statistics, styles and backtests — pure, no I/O.

None of this predicts anything. Draws are independent; every number has the
same chance every draw. What this module does is describe the past honestly:
each count comes with the range pure chance produces, and the backtest replays
each style against real draws so the claim "a hot/cold number is better" can be
checked instead of believed.

Counting rule: a number counts once per draw it appears in (presence), and the
expected values use the same rule.
"""

from __future__ import annotations

import math

from . import lotto

# Categories a frequency table can be built from. near1 is left out on purpose:
# it is always first prize ±1, so it would double-count first prize's
# neighbourhood instead of adding an independent number.
CATEGORIES = {
    2: {"last2": ("last2",)},
    3: {
        # the exact 3-digit targets a pick is scored against
        "targets": ("first", "last3f", "last3b"),
        "first3": ("first",),
        "last3f": ("last3f",),
        "last3b": ("last3b",),
        # last three digits of every prize (first..fifth) plus front/back three
        "all": ("first", "second", "third", "fourth", "fifth", "last3f", "last3b"),
    },
}
STYLES = ("random", "hot", "cold", "overdue")
# A style draws from the best quarter of the pool by its metric (ties kept),
# never fewer numbers than it has to pick.
STYLE_SHARE = 0.25
# Two-sided 1% — a Bonferroni-style bar because five strategies are compared at
# once, and one of them will look "significant" at 5% by luck alone.
Z_SIGNIFICANT = 2.58


def universe(digits: int) -> list[str]:
    return sorted(lotto.ALL_TWO if digits == 2 else lotto.ALL_THREE)


def category_numbers(prizes: dict, digits: int, category: str) -> list[str]:
    """Numbers drawn in this category, with repeats (used for the per-draw size)."""
    out = []
    for key in CATEGORIES[digits][category]:
        for num in prizes.get(key, []):
            if isinstance(num, str) and num.isdigit() and len(num) >= digits:
                out.append(num[-digits:])
    return out


def style_category(digits: int) -> str:
    return "last2" if digits == 2 else "targets"


def targets(prizes: dict, digits: int) -> set[str]:
    t = lotto.targets(prizes, digits)
    return set().union(*t.values())


# --- distributions -----------------------------------------------------------


def _binom_pmf(n: int, p: float) -> list[float]:
    if p <= 0:
        return [1.0] + [0.0] * n
    if p >= 1:
        return [0.0] * n + [1.0]
    lp, lq = math.log(p), math.log1p(-p)
    return [
        math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq)
        for k in range(n + 1)
    ]


def _cdf(pmf: list[float]) -> list[float]:
    out, acc = [], 0.0
    for v in pmf:
        acc += v
        out.append(min(acc, 1.0))
    return out


def _quantile(cdf: list[float], q: float) -> int:
    return next((k for k, v in enumerate(cdf) if v >= q), len(cdf) - 1)


def chance_profile(n: int, p: float, size: int) -> dict:
    """What pure chance gives ``size`` numbers, each in a draw with probability
    ``p``, over ``n`` draws: a 95% band per number, the usual largest and smallest
    count across all of them, and how many land outside the band by luck."""
    pmf = _binom_pmf(n, p)
    cdf = _cdf(pmf)
    lo, hi = _quantile(cdf, 0.025), _quantile(cdf, 0.975)
    outside = (cdf[lo - 1] if lo > 0 else 0.0) + (1 - cdf[hi])
    # max of `size` independent counts: P(max <= m) = F(m)^size
    max_cdf = [v ** size for v in cdf]
    # min: P(min >= m) = (1 - F(m-1))^size  →  P(min <= m) = 1 - (1 - F(m))^size
    min_cdf = [1 - (1 - v) ** size for v in cdf]
    return {
        "expected": round(n * p, 2),
        "band": [lo, hi],
        "max_typical": [_quantile(max_cdf, 0.5), _quantile(max_cdf, 0.95)],
        "min_typical": [_quantile(min_cdf, 0.05), _quantile(min_cdf, 0.5)],
        "outside_expected": round(outside * size, 1),
    }


# --- frequency ---------------------------------------------------------------


def counts_and_gaps(draws: list[dict], digits: int, category: str) -> tuple[dict, dict, dict]:
    """``draws`` newest first. Returns count, gap (draws since last seen; never
    seen = len(draws)) and last-seen date per number."""
    numbers = universe(digits)
    counts = dict.fromkeys(numbers, 0)
    gaps = dict.fromkeys(numbers, len(draws))
    last = dict.fromkeys(numbers)
    for i, d in enumerate(draws):
        for num in set(category_numbers(d["prizes"], digits, category)):
            counts[num] += 1
            if last[num] is None:
                last[num] = d["date"]
                gaps[num] = i
    return counts, gaps, last


def presence_probability(draws: list[dict], digits: int, category: str) -> float:
    """Average chance a given number shows up in one draw of this category."""
    if not draws:
        return 0.0
    size = len(universe(digits))
    return sum(
        1 - (1 - 1 / size) ** len(category_numbers(d["prizes"], digits, category)) for d in draws
    ) / len(draws)


def frequency(draws: list[dict], digits: int, category: str) -> dict:
    numbers = universe(digits)
    counts, gaps, last = counts_and_gaps(draws, digits, category)
    p = presence_probability(draws, digits, category)
    chance = chance_profile(len(draws), p, len(numbers))
    lo, hi = chance["band"]
    rows = [
        {"number": n, "count": counts[n], "gap": gaps[n], "last": last[n],
         "band": "high" if counts[n] > hi else "low" if counts[n] < lo else "normal"}
        for n in numbers
    ]
    return {
        "digits": digits,
        "category": category,
        "draws": len(draws),
        "from": draws[-1]["date"] if draws else None,
        "to": draws[0]["date"] if draws else None,
        "probability": round(p, 5),
        **chance,
        "max_seen": max(counts.values(), default=0),
        "min_seen": min(counts.values(), default=0),
        "outside": sum(1 for r in rows if r["band"] != "normal"),
        "numbers": rows,
    }


# --- styles ------------------------------------------------------------------


def style_candidates(
    pool: list[str], counts: dict, gaps: dict, style: str, k: int,
) -> list[str]:
    """The numbers a style picks from at random. ``random`` is the whole pool;
    the others keep the best quarter by their metric, ties at the cut included,
    so the result never depends on how equal counts happen to be ordered."""
    if style == "random" or not pool:
        return list(pool)
    metric = {
        "hot": lambda n: counts.get(n, 0),
        "cold": lambda n: -counts.get(n, 0),
        "overdue": lambda n: gaps.get(n, 0),
    }[style]
    ranked = sorted(pool, key=metric, reverse=True)
    take = min(len(ranked), max(k, math.ceil(len(ranked) * STYLE_SHARE)))
    cut = metric(ranked[take - 1])
    return sorted(n for n in ranked if metric(n) >= cut)


def reasons(numbers: list[str], counts: dict, gaps: dict, window: int) -> dict:
    return {n: {"count": counts.get(n, 0), "gap": gaps.get(n, window)} for n in numbers}


# --- backtest ----------------------------------------------------------------


def backtest(
    draws: list[dict],
    digits: int,
    picks: int,
    exclude_draws: int,
    scope: str,
    permute: bool,
    window: int = 0,
    min_history: int = 24,
) -> dict:
    """Replay every style over real history, using only draws before each one.

    For each draw t: exclusion uses the ``exclude_draws`` draws before t, a
    style's counts use ``window`` draws before t (0 = all of them). A style
    buys ``picks`` numbers uniformly from its candidates, so its expected hits
    on draw t are exact — ``k * |candidates ∩ targets| / |candidates|`` — and
    no random seed decides the verdict.
    """
    ordered = sorted(draws, key=lambda d: d["date"])  # oldest first
    size = len(universe(digits))
    category = style_category(digits)
    if digits == 2:
        scope = "last2"
    strategies = ["baseline", *STYLES]
    hits = dict.fromkeys(strategies, 0.0)
    bought = dict.fromkeys(strategies, 0)
    variance = dict.fromkeys(strategies, 0.0)
    series = {s: [] for s in strategies}
    dates = []
    start = max(min_history, exclude_draws, window if window else 0)
    for t in range(start, len(ordered)):
        before = ordered[:t][::-1]  # newest first
        win = before[:window] if window else before
        counts, gaps, _ = counts_and_gaps(win, digits, category)
        excluded = lotto.excluded(before[:exclude_draws], scope, permute, digits)
        pool = [n for n in universe(digits) if n not in excluded]
        goal = targets(ordered[t]["prizes"], digits)
        p0 = len(goal) / size
        dates.append(ordered[t]["date"])
        for s in strategies:
            cands = universe(digits) if s == "baseline" else style_candidates(pool, counts, gaps, s, picks)
            k = min(picks, len(cands))
            if k:
                hits[s] += k * len(goal.intersection(cands)) / len(cands)
                # Null variance of that *expected* count: |C ∩ T| is about
                # Binomial(|T|, q) with q = |C| / U, scaled by k / |C|. Using a
                # realised count's k*p*(1-p) instead deflates z 2.5x (2 digits)
                # to 8x (3 digits) and nothing could ever look significant.
                q = len(cands) / size
                variance[s] += (k / len(cands)) ** 2 * len(goal) * q * (1 - q)
            bought[s] += k
            series[s].append(round(hits[s] - bought[s] * p0, 3))
    plays = len(dates)
    base_rate = (
        sum(len(targets(d["prizes"], digits)) for d in ordered[start:]) / (plays * size)
        if plays else 0.0
    )
    rows = []
    for s in strategies:
        expected = bought[s] * base_rate
        z = (hits[s] - expected) / math.sqrt(variance[s]) if variance[s] else 0.0
        rows.append({
            "strategy": s,
            "numbers": bought[s],
            "hits": round(hits[s], 2),
            "expected": round(expected, 2),
            "ratio": round(hits[s] / expected, 3) if expected else None,
            "z": round(z, 2),
            "significant": abs(z) >= Z_SIGNIFICANT,
        })
    return {
        "digits": digits,
        "plays": plays,
        "from": dates[0] if dates else None,
        "to": dates[-1] if dates else None,
        "settings": {"picks": picks, "exclude_draws": exclude_draws, "scope": scope,
                     "permute": permute, "window": window},
        "z_threshold": Z_SIGNIFICANT,
        "strategies": rows,
        "series": {"dates": dates, **series},
    }
