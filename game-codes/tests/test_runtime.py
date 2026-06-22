import game_code_notifier as g


def test_first_run_seeds_silently():
    state = {"seen": {}, "health": {}}
    entries = [{"code": "AAA", "reward": ""}, {"code": "BBB", "reward": ""}]
    new = g.diff_new({"key": "genshin"}, entries, state)
    assert new == []                                  # nothing reported first time
    assert set(state["seen"]["genshin"]) == {"AAA", "BBB"}  # but all recorded


def test_second_run_reports_only_new():
    state = {"seen": {"genshin": ["AAA"]}, "health": {}}
    entries = [{"code": "AAA", "reward": ""}, {"code": "CCC", "reward": ""}]
    new = g.diff_new({"key": "genshin"}, entries, state)
    assert [e["code"] for e in new] == ["CCC"]
    assert set(state["seen"]["genshin"]) == {"AAA", "CCC"}
