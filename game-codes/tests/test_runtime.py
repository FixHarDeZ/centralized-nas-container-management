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


def test_expect_nonzero_source_alerts_once_then_recovers(monkeypatch):
    src = {
        "key": "rise_of_eros",
        "name": "Rise of Eros",
        "type": "section_regex",
        "url": "https://example.invalid/roe",
        "expect_nonzero": True,
        "redeem_url": None,
    }
    monkeypatch.setattr(g, "SOURCES", [src])
    monkeypatch.setattr(g, "save_state", lambda state: None)
    alerts = []
    monkeypatch.setattr(g, "send_telegram", lambda text: alerts.append(text))

    state = {"seen": {}, "health": {}}

    # First run: fetch succeeds but returns zero codes -> should alert once
    # and flip health to broken.
    monkeypatch.setattr(g, "fetch", lambda s: [])
    g.run_once(state)
    assert len(alerts) == 1
    assert "0 โค้ด" in alerts[0] or "0" in alerts[0]
    assert state["health"]["rise_of_eros"] == "broken"

    # Second run: still zero codes -> edge-only, no further alert.
    g.run_once(state)
    assert len(alerts) == 1
    assert state["health"]["rise_of_eros"] == "broken"

    # Third run: codes come back -> recovery alert, health flips to ok.
    monkeypatch.setattr(g, "fetch", lambda s: [{"code": "ROE12345678", "reward": ""}])
    g.run_once(state)
    assert len(alerts) == 2
    assert "กลับมาทำงานแล้ว" in alerts[1]
    assert state["health"]["rise_of_eros"] == "ok"
