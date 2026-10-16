from app import messages


def test_auto_messages_identify_two_and_three_digit_modes():
    base = {
        "numbers": ["07", "00"],
        "pool_size": 98,
        "settings": {"digits": 2, "draws": 2, "scope": "last2", "permute": True},
    }
    text = messages.auto_pick("2026-10-16", base)
    assert "2 ตัว" in text and "07" in text and "เลขท้าย 2 ตัว" in text
    assert "เลขกลับ" in text and "โต๊ด" not in text
    three = {
        **base,
        "numbers": ["007"],
        "settings": {**base["settings"], "digits": 3, "scope": "all", "permute": False},
    }
    assert "3 ตัว" in messages.auto_pick("2026-10-16", three)


def test_two_digit_result_uses_exact_last2_label_and_own_stats():
    draw = {
        "date": "2026-10-16",
        "prizes": {
            "first": ["123456"],
            "last3f": ["007", "123"],
            "last3b": ["456", "789"],
            "last2": ["07"],
        },
    }
    pick = {
        "source": "manual",
        "numbers": ["07"],
        "settings": {"digits": 2},
        "result": {"hits": [{"number": "07", "kinds": ["last2"]}]},
    }
    text = messages.result(
        draw,
        [pick],
        {"picks": 1, "numbers": 1, "exact_hits": 1, "expected": 0.01},
        digits=2,
    )
    assert (
        "2 ตัว" in text and "เลขท้าย 2 ตัว" in text and "✅07" in text and "0.01" in text
    )
    assert "เลขหน้า 3 ตัว" not in text
