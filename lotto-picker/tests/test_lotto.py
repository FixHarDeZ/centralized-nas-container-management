import datetime as dt
import json
import random
from pathlib import Path

from app import lotto

FIX = Path(__file__).parent / "fixtures"


def load(name):
    resp = json.loads((FIX / name).read_text())["response"]
    return {"date": resp["date"], "prizes": lotto.parse_prizes(resp["data"])}


OCT1 = load("latest_2026-10-01.json")
JAN17 = load("result_2026-01-17.json")


def test_real_payloads_parse_complete():
    assert lotto.is_complete(OCT1["prizes"])
    assert lotto.is_complete(JAN17["prizes"])
    assert OCT1["prizes"]["first"] == ["402701"]
    assert OCT1["prizes"]["last3b"] == ["058", "396"]


def test_incomplete_draw_is_not_complete():
    partial = {**OCT1["prizes"], "fifth": OCT1["prizes"]["fifth"][:40]}
    assert not lotto.is_complete(partial)


def test_placeholder_values_are_not_complete():
    for key, bad in (("fifth", "xxxxxx"), ("first", "4027"), ("last3b", "05-"), ("last2", "x")):
        prizes = {k: list(v) for k, v in OCT1["prizes"].items()}
        prizes[key][0] = bad
        assert not lotto.is_complete(prizes), key


def test_all_scope_takes_last3_of_every_prize_and_skips_last2():
    nums = lotto.draw_numbers(OCT1["prizes"])
    assert "701" in nums  # first 402701
    assert {"791", "912", "058", "396"} <= nums
    assert "700" in nums and "702" in nums  # near1
    assert "70" not in nums and all(len(n) == 3 for n in nums)
    # 172 prize numbers before de-dup
    assert 140 <= len(nums) <= 172


def test_front_back_scope_is_only_the_four_3digit_numbers():
    assert lotto.draw_numbers(OCT1["prizes"], "front_back") == {"791", "912", "058", "396"}


def test_pool_never_contains_excluded_numbers():
    draws = [OCT1, JAN17]
    ex = lotto.excluded(draws)
    pool = lotto.pool(draws)
    assert not ex & set(pool)
    assert len(ex) + len(pool) == 1000
    picked = lotto.pick(pool, 5, random.Random(1))
    assert len(set(picked)) == 5 and not set(picked) & ex


def test_permute_excludes_every_ordering():
    draw = {"date": "x", "prizes": {"last3f": ["058"], "last3b": ["111"]}}
    ex = lotto.excluded([draw], "front_back", permute=True)
    assert ex == {"058", "085", "508", "580", "805", "850", "111"}


def test_pick_caps_at_pool_size():
    assert lotto.pick(["001", "002"], 5) == ["001", "002"]
    assert lotto.pick([], 5) == []


def test_score_exact_and_tod():
    s = lotto.score(["701", "107", "058", "123"], OCT1["prizes"])
    by = {h["number"]: h["kinds"] for h in s["hits"]}
    assert by["701"] == ["first3"]
    assert by["107"] == ["first3_tod"]
    assert by["058"] == ["last3b"]
    assert "123" not in by
    assert s["exact_hits"] == 2  # tod is not an exact hit
    # 5 distinct exact targets (701, 791, 912, 058, 396) x 4 numbers / 1000
    assert s["expected"] == 4 * 5 / 1000


def test_next_expected_draw():
    assert lotto.next_expected_draw(dt.date(2026, 10, 1)) == dt.date(2026, 10, 16)
    assert lotto.next_expected_draw(dt.date(2026, 10, 16)) == dt.date(2026, 11, 1)
    assert lotto.next_expected_draw(dt.date(2026, 12, 30)) == dt.date(2027, 1, 1)
    assert lotto.next_expected_draw(dt.date(2026, 1, 17)) == dt.date(2026, 2, 1)


def test_thai_date():
    assert lotto.thai_date("2026-10-01") == "1 ต.ค. 2569"
