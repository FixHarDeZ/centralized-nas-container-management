"""Opt-in browser tests for stats, backtest, summary, 6-digit helper and ledger.

Runs the real FastAPI app on a seeded temp DB (not a fixture server), with GLO,
the scheduler and mimo switched off — every view here talks to real endpoints.
"""

import datetime as dt
import os
import random
import socket
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LOTTO_UI_BROWSER") != "1", reason="Set LOTTO_UI_BROWSER=1"
)


def seeded_draws(n=60, seed=7):
    rng = random.Random(seed)
    from app import lotto

    day = dt.date(2024, 1, 1)
    out = []
    for _ in range(n):
        prizes = {k: [f"{rng.randrange(1_000_000):06d}" for _ in range(c)]
                  for k, c in lotto.EXPECTED_COUNTS.items()}
        prizes["last3f"] = [f"{rng.randrange(1000):03d}" for _ in range(2)]
        prizes["last3b"] = [f"{rng.randrange(1000):03d}" for _ in range(2)]
        prizes["last2"] = [f"{rng.randrange(100):02d}"]
        out.append({"date": day.isoformat(), "prizes": prizes})
        day = lotto.next_expected_draw(day)
    return out


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        instance = runtime.chromium.launch(channel="chrome", headless=True)
        yield instance
        instance.close()


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    import uvicorn
    from app import db, lotto, main, service

    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    monkeypatch.setattr(lotto, "HISTORY_START", dt.date(2024, 1, 1))
    monkeypatch.setattr(service, "sync", lambda *a, **k: None)
    monkeypatch.setattr(service, "backfill_history", lambda *a, **k: {})
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.setattr(main, "_scheduler", type("S", (), {
        "add_job": lambda *a, **k: None, "start": lambda *a: None,
        "shutdown": lambda *a, **k: None,
    })())
    service._cache.clear()
    db.init()
    draws = seeded_draws()
    for d in draws:
        db.add_draw(d)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", draws
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def page(browser, app_url):
    context = browser.new_context(viewport={"width": 390, "height": 844},
                                  permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.set_default_timeout(8000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(app_url[0])
    page.wait_for_function("document.getElementById('draws').value === '2'")
    yield page
    context.close()
    assert not errors, errors


def nav(page, name):
    page.get_by_role("button", name=name, exact=True).click()


def no_horizontal_scroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_two_digit_heatmap_ranks_lookup_backtest_and_summary(page):
    page.locator("#mode-two").click()
    nav(page, "สถิติ")
    page.locator(".heat-cell").first.wait_for()
    assert page.locator(".heat-cell").count() == 100
    assert page.locator("#category-field").is_hidden()
    assert "60 งวด" in page.locator("#history-info").inner_text()
    assert page.locator("#rank-hot li").count() == 10
    assert page.locator("#freq-verdict").inner_text()
    page.locator(".heat-cell").nth(7).click()
    assert page.locator("#lookup-result").inner_text().startswith("07:")
    page.locator("#run-backtest").click()
    page.locator(".bt-table tbody tr").first.wait_for()
    assert page.locator(".bt-table tbody tr").count() == 5
    assert page.locator(".bt-chart polyline").count() == 4
    page.locator("#run-insight").click()
    page.wait_for_function("document.getElementById('insight-text').textContent.includes('สถิติย้อนหลังใช้ทำนายไม่ได้')", timeout=15000)
    assert "อัตโนมัติ" in page.locator("#insight-source").inner_text()
    assert no_horizontal_scroll(page)


def test_three_digit_categories_hide_heatmap(page):
    nav(page, "สถิติ")
    page.locator("#freq-facts .fact").first.wait_for()
    assert page.locator("#heatmap").is_hidden()
    page.locator("#category").select_option("all")
    page.wait_for_function("document.querySelector('#freq-facts .fact strong') && Number(document.querySelector('#freq-facts .fact strong').textContent) > 5")
    page.locator("#lookup").fill("123")
    page.locator("#lookup-form button").click()
    assert page.locator("#lookup-result").inner_text().startswith("123:")


def test_style_pick_shows_reasons_and_six_digit_patterns(page):
    page.locator(".advanced-details summary").click()
    page.locator("#style").select_option("hot")
    page.locator("#go").click()
    page.locator("#reasons li").first.wait_for()
    assert page.locator("#reasons li").count() == 5
    assert "ออก" in page.locator("#reasons li").first.inner_text()
    assert "สไตล์ตามกระแส" in page.locator("#poolInfo").inner_text()
    page.locator(".six-details summary").click()
    patterns = page.locator(".six-list b").all_inner_texts()
    assert len(patterns) == 10 and patterns[0].startswith("xxx") and patterns[1].endswith("xxx")
    page.locator("#six-copy").click()
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied.splitlines() == patterns


def test_ticket_check_and_ledger(page, app_url):
    draws = app_url[1]
    latest = draws[-1]
    nav(page, "ผลรางวัล")
    page.locator("#check-date option").first.wait_for(state="attached")
    winning = "000" + latest["prizes"]["last3b"][0]
    page.locator("#check-number").fill(winning)
    page.locator("#check-form button").click()
    page.wait_for_function("document.getElementById('check-result').textContent.includes('เลขท้าย 3 ตัว')")

    nav(page, "บัญชี")
    assert page.locator(".mode-selector").is_hidden()
    page.locator("#ledger-summary .fact").first.wait_for()
    page.locator("#ledger-date").select_option(latest["date"])
    page.locator("#ledger-tickets").fill(f"{winning}\n111111 x2")
    assert page.locator("#ledger-cost").input_value() == "240"
    page.locator("#ledger-label").fill("แผงหน้าบ้าน")
    page.locator("#ledger-save").click()
    page.locator(".ledger-card").first.wait_for()
    card = page.locator(".ledger-card").first.inner_text()
    assert "ถูกรางวัล" in card and "แผงหน้าบ้าน" in card
    summary = page.locator("#ledger-summary").inner_text()
    assert "240" in summary and "60%" in summary
    page.once("dialog", lambda d: d.accept())
    page.locator(".ledger-card .del").click()
    page.locator("#ledger-list .empty-state").wait_for()
    assert no_horizontal_scroll(page)


@pytest.mark.parametrize("width", [320, 768, 1280])
def test_new_views_fit_every_width(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    for view in ("สถิติ", "บัญชี", "ผลรางวัล"):
        nav(page, view)
        page.wait_for_timeout(300)
        assert no_horizontal_scroll(page), view
