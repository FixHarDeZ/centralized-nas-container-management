"""Pure lottery logic — no I/O, so tests run without the network or a DB.

A Draw here is ``{"date": "YYYY-MM-DD", "prizes": {key: [numbers]}}`` where the
keys are GLO's own (``first`` ... ``fifth``, ``near1``, ``last3f``, ``last3b``,
``last2``).
"""

from __future__ import annotations

import datetime as dt
import itertools
import random

ALL_THREE = {f"{i:03d}" for i in range(1000)}
ALL_TWO = {f"{i:02d}" for i in range(100)}

# Every prize a ticket can win, by how many numbers GLO draws for it. A result
# with fewer is still being drawn (GLO publishes live during the afternoon) and
# must not be cached as final — every later exclusion pool would be wrong.
EXPECTED_COUNTS = {
    "first": 1,
    "second": 5,
    "third": 10,
    "fourth": 50,
    "fifth": 100,
    "near1": 2,
    "last3f": 2,
    "last3b": 2,
}

# Digits per number. A count alone can't tell a finished draw from a payload
# padded with placeholders while the draw is live.
DIGITS = {"first": 6, "second": 6, "third": 6, "fourth": 6, "fifth": 6,
          "near1": 6, "last3f": 3, "last3b": 3, "last2": 2}

SCOPES = {
    # last 3 digits of every prize + front/back three
    "all": tuple(EXPECTED_COUNTS),
    # only the two 3-digit prizes
    "front_back": ("last3f", "last3b"),
}

# Draws normally fall on the 1st and 16th but move for holidays (17 Jan, 2 May,
# 30 Dec seen). Probing only these days keeps a history backfill to ~5 requests
# per draw instead of 15.
CANDIDATE_DAYS = {1, 2, 3, 15, 16, 17, 28, 29, 30, 31}

# First draw with today's prize shape (two front-3 and two back-3 numbers).
# Before it GLO serves four back-3 numbers and no front-3, which would make the
# 3-digit statistics mean different things over time — history stops here.
HISTORY_START = dt.date(2015, 9, 1)

# Baht per ticket, by prize. GLO sends these as ``price`` with every result
# (unchanged since HISTORY_START); the latest payload's values override these.
PRIZE_AMOUNTS = {
    "first": 6_000_000, "second": 200_000, "third": 80_000, "fourth": 40_000,
    "fifth": 20_000, "near1": 100_000, "last3f": 4_000, "last3b": 4_000, "last2": 2_000,
}
TICKET_PRICE = 80
SIX_DIGIT_PRIZES = ("first", "second", "third", "fourth", "fifth", "near1")

THAI_MONTHS = (
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
)


def parse_amounts(data: dict) -> dict[str, int]:
    """GLO ``response.data`` → ``{key: baht}`` from each prize's ``price``."""
    out = {}
    for key, prize in (data or {}).items():
        try:
            out[key] = int(float(prize.get("price")))
        except (TypeError, ValueError):
            continue
    return out


def parse_prizes(data: dict) -> dict[str, list[str]]:
    """GLO ``response.data`` → ``{key: ["402701", ...]}``.

    ``n3`` (the separate N3 product) is a sibling of ``data``, never inside it,
    so it can't leak in here.
    """
    return {
        key: [n["value"] for n in prize.get("number", []) if n.get("value")]
        for key, prize in (data or {}).items()
    }


def has_last2(prizes: dict[str, list[str]]) -> bool:
    """Whether the official last-two prize has exactly one usable number."""
    numbers = prizes.get("last2", [])
    return len(numbers) == 1 and all(
        isinstance(n, str) and n.isascii() and n.isdigit() and len(n) == 2
        for n in numbers
    )


def is_complete(prizes: dict[str, list[str]]) -> bool:
    # Keep last2 separate: EXPECTED_COUNTS also defines the legacy all-three
    # exclusion scope and must never start including the two-digit prize.
    if not has_last2(prizes):
        return False
    if any(len(prizes.get(k, [])) != n for k, n in EXPECTED_COUNTS.items()):
        return False
    return all(
        isinstance(num, str) and num.isascii() and num.isdigit() and len(num) == DIGITS[k]
        for k in DIGITS
        for num in prizes.get(k, [])
    )


def draw_numbers(prizes: dict[str, list[str]], scope: str = "all", digits: int = 3) -> set[str]:
    """Numbers a draw used in the selected mode; two digits uses last2 only."""
    if digits == 2:
        return {
            n for n in prizes.get("last2", [])
            if isinstance(n, str) and n.isascii() and n.isdigit() and len(n) == 2
        }
    out = set()
    for key in SCOPES[scope]:
        for num in prizes.get(key, []):
            if len(num) >= 3:
                out.add(num[-3:])
    return out


def permutations(num: str) -> set[str]:
    return {"".join(p) for p in itertools.permutations(num)}


def excluded(
    draws: list[dict], scope: str = "all", permute: bool = False, digits: int = 3,
) -> set[str]:
    out: set[str] = set()
    for d in draws:
        out |= draw_numbers(d["prizes"], scope, digits)
    if permute:
        out = set().union(*(permutations(n) for n in out)) if out else set()
    return out


def pool(
    draws: list[dict], scope: str = "all", permute: bool = False, digits: int = 3,
) -> list[str]:
    universe = ALL_TWO if digits == 2 else ALL_THREE
    return sorted(universe - excluded(draws, scope, permute, digits))


def pick(available: list[str], k: int, rng: random.Random | None = None) -> list[str]:
    """Up to k distinct numbers; fewer when the pool is smaller than k."""
    rng = rng or random.SystemRandom()
    return sorted(rng.sample(available, min(k, len(available))))


def targets(prizes: dict[str, list[str]], digits: int = 3) -> dict[str, set[str]]:
    """Official exact targets for the selected number width."""
    if digits == 2:
        return {"last2": draw_numbers(prizes, digits=2)}
    first = prizes.get("first", [])
    return {
        "first3": {n[-3:] for n in first},
        "last3f": set(prizes.get("last3f", [])),
        "last3b": set(prizes.get("last3b", [])),
    }


def score(numbers: list[str], prizes: dict[str, list[str]], digits: int = 3) -> dict:
    """Hits per number plus the hit count a uniform random pick would expect.

    ``expected`` is the honest baseline: each number hits an exact target with
    probability (distinct targets / universe size), whatever exclusion was applied.
    """
    t = targets(prizes, digits)
    if digits == 2:
        hits = [{"number": num, "kinds": ["last2"]} for num in numbers if num in t["last2"]]
        return {
            "hits": hits,
            "exact_hits": len(hits),
            "expected": len(numbers) * len(t["last2"]) / 100,
        }
    exact = t["first3"] | t["last3f"] | t["last3b"]
    hits = []
    for num in numbers:
        kinds = [k for k in ("first3", "last3f", "last3b") if num in t[k]]
        if not kinds and any(
            num != f and sorted(num) == sorted(f) for f in t["first3"]
        ):
            kinds.append("first3_tod")
        if kinds:
            hits.append({"number": num, "kinds": kinds})
    exact_hits = sum(1 for h in hits if h["kinds"] != ["first3_tod"])
    return {
        "hits": hits,
        "exact_hits": exact_hits,
        "expected": len(numbers) * len(exact) / 1000,
    }


def next_expected_draw(after: dt.date) -> dt.date:
    """Next 1st/16th strictly after ``after`` — the nominal schedule only."""
    if after.day < 16:
        return after.replace(day=16)
    nxt = (after.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return nxt


def thai_date(d: str | dt.date) -> str:
    if isinstance(d, str):
        d = dt.date.fromisoformat(d)
    return f"{d.day} {THAI_MONTHS[d.month - 1]} {d.year + 543}"


def ticket_prizes(number: str, prizes: dict[str, list[str]]) -> list[str]:
    """Every prize one 6-digit ticket wins — a ticket can win several at once
    (first prize also matches its own back-3 and last-2, for example)."""
    won = [k for k in SIX_DIGIT_PRIZES if number in prizes.get(k, [])]
    if number[:3] in prizes.get("last3f", []):
        won.append("last3f")
    if number[-3:] in prizes.get("last3b", []):
        won.append("last3b")
    if number[-2:] in prizes.get("last2", []):
        won.append("last2")
    return won


def ticket_value(number: str, prizes: dict[str, list[str]], amounts: dict[str, int]) -> int:
    return sum(amounts.get(k, PRIZE_AMOUNTS[k]) for k in ticket_prizes(number, prizes))


def expected_return(amounts: dict[str, int], price: float = TICKET_PRICE) -> float:
    """Average baht back per baht spent on one ticket, from the prize table:
    each prize pays ``amount`` with probability ``count / its universe``."""
    a = {**PRIZE_AMOUNTS, **amounts}
    value = sum(a[k] * EXPECTED_COUNTS[k] for k in SIX_DIGIT_PRIZES) / 1_000_000
    value += (a["last3f"] * 2 + a["last3b"] * 2) / 1000 + a["last2"] / 100
    return value / price
