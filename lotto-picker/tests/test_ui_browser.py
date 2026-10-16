"""Opt-in browser acceptance tests; fixture server never contacts GLO or Telegram."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LOTTO_UI_BROWSER") != "1", reason="Set LOTTO_UI_BROWSER=1"
)
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        instance = runtime.chromium.launch(channel="chrome", headless=True)
        yield instance
        instance.close()


@pytest.fixture
def ui(browser):
    state = {
        "settings": {
            "digits": 3,
            "draws": 2,
            "picks": 5,
            "scope": "all",
            "permute": False,
            "notify": True,
        },
        "numbers": ["007", "058", "123", "456", "890"],
        "draws": [
            {
                "date": "2026-10-01",
                "first": "123007",
                "last3f": ["058", "456"],
                "last3b": ["123", "789"],
                "last2": ["09"],
                "count": 155,
            }
        ],
        "picks": [],
        "requests": [],
        "failures": {},
        "delays": {},
        "stats": {
            "picks": 0,
            "numbers": 0,
            "exact_hits": 0,
            "tod_hits": 0,
            "expected": 0,
        },
    }

    state.update(
        settings_2={
            **state["settings"],
            "digits": 2,
            "scope": "last2",
            "notify": False,
        },
        numbers_2=["00", "07", "12", "45", "89"],
        picks_2=[],
        stats_2={**state["stats"]},
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def handle_request(self):
            key = f"{self.command} {self.path}"
            url = urlsplit(self.path)
            path = url.path
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", 0))) or "null"
            )
            digits = int(parse_qs(url.query).get("digits", [3])[0])
            if body:
                digits = body.get(
                    "digits", body.get("settings", {}).get("digits", digits)
                )
            suffix = "_2" if digits == 2 else ""
            state["requests"].append((key, body))
            time.sleep(state["delays"].get(key, 0))
            if state["failures"].get(key, 0):
                state["failures"][key] -= 1
                return self.reply({"detail": "Temporary failure"}, 503)
            if path == "/api/settings":
                if self.command == "PUT":
                    state["settings" + suffix] = body
                return self.reply(state["settings" + suffix])
            if path == "/api/draws":
                return self.reply(state["draws"])
            if path == "/api/stats":
                return self.reply(state["stats" + suffix])
            if path == "/api/pick":
                return self.reply(
                    {
                        "numbers": state["numbers" + suffix],
                        "settings": body,
                        "excluded": ["01", "02"] if digits == 2 else ["001", "002"],
                        "excluded_count": 2,
                        "pool_size": (98 if digits == 2 else 998)
                        if state["numbers" + suffix]
                        else 0,
                        "draws_used": ["2026-10-01"],
                    }
                )
            if path == "/api/picks":
                if self.command == "POST":
                    pick_id = (
                        max(
                            (
                                pick["id"]
                                for name in ("picks", "picks_2")
                                for pick in state[name]
                            ),
                            default=0,
                        )
                        + 1
                    )
                    state["picks" + suffix].insert(
                        0,
                        {
                            "id": pick_id,
                            "numbers": body["numbers"],
                            "settings": body["settings"],
                            "source": "manual",
                            "created_at": "2026-10-16 09:00:00",
                            "based_on": "2026-10-01",
                            "result_draw": None,
                            "result": None,
                        },
                    )
                    return self.reply({"id": pick_id}, 201)
                return self.reply(state["picks" + suffix])
            if self.path.startswith("/api/picks/") and self.command == "DELETE":
                for name in ("picks", "picks_2"):
                    state[name] = [
                        pick
                        for pick in state[name]
                        if pick["id"] != int(path.rsplit("/", 1)[1])
                    ]
                return self.reply(None, 204)
            if path == "/api/sync":
                return self.reply({"draws": 1, "latest_seen": "2026-10-01"})
            filename = (
                "index.html" if self.path == "/" else self.path.removeprefix("/static/")
            )
            if filename not in {"index.html", "style.css", "app.js"}:
                return self.reply({}, 404)
            content_type = {
                "html": "text/html",
                "css": "text/css",
                "js": "text/javascript",
            }[filename.rsplit(".", 1)[1]]
            data = (STATIC / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)

        def reply(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if data is not None:
                self.wfile.write(json.dumps(data).encode())

        do_GET = do_POST = do_PUT = do_DELETE = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    page.set_default_timeout(5000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(origin)
    page.wait_for_function("document.getElementById('draws').value === '2'")
    yield page, state
    context.close()
    server.shutdown()
    server.server_close()
    thread.join()
    assert not errors, errors


def test_navigation_and_bounded_mobile_controls(ui):
    page, _ = ui
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    assert page.locator("#view-history").is_visible()
    assert page.locator("#view-pick").is_hidden()
    page.get_by_role("button", name="ผลรางวัล", exact=True).click()
    assert "123007" in page.locator("#draws-list").inner_text()
    page.get_by_role("button", name="สุ่มเลข", exact=True).last.click()
    page.locator("#draws").fill("24")
    assert page.locator('[data-step-target="draws"][data-step="1"]').is_disabled()
    page.locator('[data-step-target="draws"][data-step="-1"]').click()
    page.locator('[data-step-target="draws"][data-step="1"]').click()
    assert page.locator("#draws").input_value() == "24"
    page.locator("#picks").fill("0")
    page.locator("#picks").blur()
    assert page.locator("#picks").input_value() == "1"


def test_roll_save_copy_and_delete_confirmation(ui):
    page, state = ui
    page.locator("#go").click()
    page.locator("#result").wait_for(state="visible")
    assert "007" in page.locator("#numbers").inner_text()
    page.locator("#copy").click()
    page.wait_for_function(
        "navigator.clipboard.readText().then(t => t.includes('007'))"
    )
    page.locator("#draws").fill("5")
    page.locator("#save").click()
    page.wait_for_function(
        "document.getElementById('result-status').textContent.includes('บันทึกแล้ว')"
    )
    posted = [body for key, body in state["requests"] if key == "POST /api/picks"]
    assert posted[0]["settings"]["draws"] == 2
    assert posted[0]["numbers"][0] == "007"
    assert page.locator("#save").is_disabled()
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    page.locator(".pick-card").wait_for()
    assert "รอผล" in page.locator("#picks-list").inner_text()
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator(".del").click()
    assert not any(key.startswith("DELETE") for key, _ in state["requests"])
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".del").click()
    page.locator(".pick-card").wait_for(state="detached")


def test_requests_disable_conflicting_actions(ui):
    page, state = ui
    state["delays"]["POST /api/pick"] = 0.3
    page.locator("#go").click()
    assert page.locator("#go").is_disabled()
    page.locator("#numbers .number-ticket").first.wait_for()
    state["delays"]["POST /api/picks"] = 0.3
    page.locator("#save").click()
    assert page.locator("#go").is_disabled()
    assert page.locator("#again").is_disabled()
    page.wait_for_function("document.getElementById('go').disabled === false")


def test_navigation_opens_destination_at_top_after_rolling(ui):
    page, state = ui
    base = {
        "numbers": state["numbers"],
        "settings": state["settings"],
        "source": "manual",
        "created_at": "2026-10-16 09:00:00",
        "based_on": "2026-10-01",
        "result_draw": None,
        "result": None,
    }
    state["picks"] = [{**base, "id": index} for index in range(15)]
    page.reload()
    page.wait_for_function("document.getElementById('go').disabled === false")
    page.locator("#go").click()
    page.locator("#result").wait_for(state="visible")
    page.evaluate(
        "window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})"
    )
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    assert page.evaluate("window.scrollY") == 0


def test_notification_failure_rolls_back_and_roll_can_retry(ui):
    page, state = ui
    page.locator("#notify").evaluate(
        "node => node.closest('details')?.setAttribute('open', '')"
    )
    state["failures"]["PUT /api/settings"] = 1
    page.locator("label").filter(has=page.locator("#notify")).click()
    page.wait_for_function("document.getElementById('notify').checked === true")
    state["failures"]["POST /api/pick"] = 1
    page.locator("#go").click()
    page.wait_for_function(
        "document.getElementById('toast').textContent.includes('สุ่มไม่สำเร็จ')"
    )
    assert page.locator("#go").is_enabled()
    page.locator("#go").click()
    page.locator("#result").wait_for(state="visible")


def test_exhausted_pool_cannot_be_saved(ui):
    page, state = ui
    state["numbers"] = []
    page.locator("#go").click()
    page.locator("#result").wait_for(state="visible")
    assert page.locator("#save").is_disabled()
    assert page.locator("#copy").is_disabled()
    assert "ไม่มีเลข" in page.locator("#numbers").inner_text()


def test_notification_preserves_draft_until_settings_are_saved(ui):
    page, state = ui
    page.locator("#notify").evaluate("node => node.closest('details').open = true")
    page.locator("#draws").fill("5")
    page.locator("label").filter(has=page.locator("#notify")).click()
    page.wait_for_function("document.getElementById('notify').disabled === false")
    assert state["settings"]["draws"] == 2
    assert state["settings"]["notify"] is False
    page.locator("#saveSettings").click()
    page.wait_for_function("document.getElementById('saveSettings').disabled === false")
    assert state["settings"]["draws"] == 5
    page.reload()
    page.wait_for_function("document.getElementById('draws').value === '5'")


def test_notification_uses_latest_settings_from_other_device(ui):
    page, state = ui
    state["settings"].update(draws=7, picks=10, scope="front_back", permute=True)
    page.locator("#notify").evaluate("node => node.closest('details').open = true")
    page.locator("label").filter(has=page.locator("#notify")).click()
    page.wait_for_function("document.getElementById('notify').disabled === false")
    assert state["settings"] == {
        "digits": 3,
        "draws": 7,
        "picks": 10,
        "scope": "front_back",
        "permute": True,
        "notify": False,
    }
    assert page.locator("#draws").input_value() == "2"


def test_failed_save_can_be_retried(ui):
    page, state = ui
    page.locator("#go").click()
    page.locator("#result").wait_for(state="visible")
    state["failures"]["POST /api/picks"] = 1
    page.locator("#save").click()
    page.wait_for_function(
        "document.getElementById('toast').textContent.includes('บันทึกไม่สำเร็จ')"
    )
    assert page.locator("#save").is_enabled()
    page.locator("#save").click()
    page.wait_for_function(
        "document.getElementById('result-status').textContent.includes('บันทึกแล้ว')"
    )
    assert len(state["picks"]) == 1


def test_failed_sections_offer_working_retries(ui):
    page, state = ui
    state["failures"] = {
        "GET /api/settings": 1,
        "GET /api/picks": 1,
        "GET /api/draws": 1,
    }
    page.reload()
    page.locator("#settingsInfo .retry").wait_for(state="attached")
    assert page.locator("#go").is_disabled()
    page.locator("#settingsInfo").evaluate(
        "node => node.closest('details').open = true"
    )
    page.locator("#settingsInfo .retry").click()
    page.wait_for_function("document.getElementById('go').disabled === false")
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    page.locator("#picks-list .retry").click()
    page.locator("#picks-list .empty-state").wait_for()
    page.get_by_role("button", name="ผลรางวัล", exact=True).click()
    page.locator("#draws-list .retry").click()
    page.locator("#draws-list .draw-card").wait_for()


def test_checked_hits_and_losses_are_distinct_from_pending(ui):
    page, state = ui
    base = {
        "numbers": ["007", "058"],
        "settings": state["settings"],
        "source": "auto",
        "created_at": "2026-10-16 09:00:00",
        "based_on": "2026-10-01",
    }
    state["picks"] = [
        {**base, "id": 3, "result_draw": None, "result": None},
        {
            **base,
            "id": 2,
            "result_draw": "2026-10-16",
            "result": {
                "hits": [{"number": "007", "kinds": ["first3_tod"]}],
                "exact_hits": 0,
                "expected": 0.01,
            },
        },
        {
            **base,
            "id": 1,
            "result_draw": "2026-10-16",
            "result": {"hits": [], "exact_hits": 0, "expected": 0.01},
        },
    ]
    state["stats"] = {
        "picks": 2,
        "numbers": 4,
        "exact_hits": 0,
        "tod_hits": 1,
        "expected": 0.02,
    }
    page.reload()
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    page.locator(".pick-card").first.wait_for()
    assert page.locator(".pick-status.pending").count() == 1
    assert page.locator(".pick-status.checked").count() == 1
    assert page.locator(".number-chip.tod").inner_text() == "007"
    assert "โต๊ด 3 ตัวท้ายรางวัลที่ 1" in page.locator(".pick-detail").inner_text()
    assert page.locator("#stat-tod").inner_text() == "1"


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_layout_and_result_visibility(ui, width):
    page, _ = ui
    page.set_viewport_size({"width": width, "height": 900})
    page.locator("#go").click()
    page.locator("#result").wait_for(state="visible")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for selector in ["#go", "#save", "#copy", "#again", "[data-view='history']"]:
        box = page.locator(selector).bounding_box()
        assert box and box["height"] >= 44, (selector, box)
    destination = os.environ.get("LOTTO_UI_SCREENSHOTS")
    if destination:
        Path(destination).mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(Path(destination) / f"lotto-{width}-light.png"),
            full_page=True,
            animations="disabled",
        )
        page.emulate_media(color_scheme="dark")
        page.screenshot(
            path=str(Path(destination) / f"lotto-{width}-dark.png"),
            full_page=True,
            animations="disabled",
        )


def select_mode(page, digits):
    page.locator(f"#mode-{'two' if digits == 2 else 'three'}").click()
    page.wait_for_function(
        "digits => document.body.dataset.digits === String(digits) && !document.getElementById('go').disabled",
        arg=digits,
    )


def test_two_digit_leading_zero_snapshot_and_settings(ui):
    page, state = ui
    assert page.locator("#mode-three").get_attribute("aria-pressed") == "true"
    select_mode(page, 2)
    assert page.locator("#scope-options").is_hidden()
    assert "เลขท้าย 2 ตัว" in page.locator("#fixed-scope").inner_text()
    assert "1 ใน 100" in page.locator("#probability-note").inner_text()
    page.locator(".advanced-details").evaluate("node => node.open = true")
    assert "ตัดเลขกลับด้วย" in page.locator("#permute-label").inner_text()
    page.locator("#permute").check(force=True)
    page.locator("#draws").fill("4")
    page.locator("#go").click()
    page.locator("#numbers .number-ticket").first.wait_for()
    assert (
        page.locator("#numbers .number-ticket").all_inner_texts() == state["numbers_2"]
    )
    page.locator("#copy").click()
    page.wait_for_function(
        "navigator.clipboard.readText().then(t => t.startsWith('00 07'))"
    )
    page.locator("#draws").fill("9")
    page.locator("#save").click()
    page.wait_for_function(
        "document.getElementById('result-status').textContent.includes('บันทึกแล้ว')"
    )
    posted = [body for key, body in state["requests"] if key == "POST /api/picks"]
    assert posted[-1]["settings"] == {
        "digits": 2,
        "draws": 4,
        "picks": 5,
        "scope": "last2",
        "permute": True,
    }
    assert posted[-1]["numbers"][:2] == ["00", "07"]
    assert state["picks"] == []
    assert len(state["picks_2"]) == 1
    page.locator("#notify").evaluate("node => node.closest('details').open = true")
    assert not page.locator("#notify").is_checked()
    page.locator("#saveSettings").click()
    page.wait_for_function("document.getElementById('saveSettings').disabled === false")
    assert state["settings_2"]["draws"] == 9
    assert state["settings_2"]["scope"] == "last2"
    assert state["settings"]["draws"] == 2
    assert state["settings"]["notify"] is True


def test_mode_drafts_results_and_saved_status_are_independent(ui):
    page, _ = ui
    page.locator(".advanced-details").evaluate("node => node.open = true")
    page.locator("#scope").select_option("front_back")
    page.locator("label").filter(has=page.locator("#permute")).click()
    page.locator("#draws").fill("7")
    page.locator("#go").click()
    page.locator("#numbers .number-ticket").first.wait_for()
    three_numbers = page.locator("#numbers").inner_text()
    page.locator("#save").click()
    page.wait_for_function(
        "document.getElementById('save').textContent.includes('บันทึกแล้ว')"
    )
    page.locator("#draws").fill("11")
    select_mode(page, 2)
    assert page.locator("#result").is_hidden()
    assert page.locator("#draws").input_value() == "2"
    assert not page.locator("#permute").is_checked()
    page.locator("#draws").fill("4")
    page.locator("#go").click()
    page.locator("#numbers .number-ticket").first.wait_for()
    two_numbers = page.locator("#numbers").inner_text()
    select_mode(page, 3)
    assert page.locator("#draws").input_value() == "11"
    assert page.locator("#scope").input_value() == "front_back"
    assert page.locator("#permute").is_checked()
    assert page.locator("#numbers").inner_text() == three_numbers
    assert page.locator("#save").is_disabled()
    select_mode(page, 2)
    assert page.locator("#draws").input_value() == "4"
    assert page.locator("#numbers").inner_text() == two_numbers
    assert page.locator("#save").is_enabled()


def test_notification_profiles_preserve_independent_unsaved_drafts(ui):
    page, state = ui
    select_mode(page, 2)
    page.locator("#draws").fill("9")
    page.locator("#notify").evaluate("node => node.closest('details').open = true")
    page.locator("label").filter(has=page.locator("#notify")).click()
    page.wait_for_function("document.getElementById('notify').disabled === false")
    assert state["settings_2"]["notify"] is True
    assert state["settings_2"]["draws"] == 2
    assert state["settings_2"]["digits"] == 2
    select_mode(page, 3)
    assert page.locator("#notify").is_checked()
    page.locator("label").filter(has=page.locator("#notify")).click()
    page.wait_for_function("document.getElementById('notify').disabled === false")
    assert state["settings"]["notify"] is False
    assert state["settings_2"]["notify"] is True
    select_mode(page, 2)
    assert page.locator("#notify").is_checked()
    assert page.locator("#draws").input_value() == "9"


def test_mode_history_stats_and_prize_labels(ui):
    page, state = ui
    base = {
        "source": "manual",
        "created_at": "2026-10-16 09:00:00",
        "based_on": "2026-10-01",
        "result_draw": "2026-10-16",
    }
    state["picks_2"] = [
        {
            **base,
            "id": 2,
            "numbers": ["07"],
            "settings": state["settings_2"],
            "result": {"hits": [{"number": "07", "kinds": ["last2"]}]},
        }
    ]
    state["stats_2"].update(picks=1, numbers=1, exact_hits=1, expected=0.01)
    select_mode(page, 2)
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    page.locator(".pick-card").wait_for()
    assert "2 ตัว" in page.locator(".mode-badge").inner_text()
    assert "เลขท้าย 2 ตัว" in page.locator(".pick-detail").inner_text()
    assert page.locator("#stat-exact").inner_text() == "1"
    assert page.locator("#stat-tod").is_hidden()
    select_mode(page, 3)
    page.wait_for_function("document.getElementById('stat-exact').textContent === '0'")
    assert page.locator("#picks-list .empty-state").is_visible()
    assert page.locator("#stat-tod").is_visible()
    page.get_by_role("button", name="ผลรางวัล", exact=True).click()
    assert page.locator("#mode-two").is_visible()
    select_mode(page, 2)
    assert page.locator("#view-draws").is_visible()


def test_mode_switch_is_blocked_during_mutations(ui):
    page, state = ui
    state["delays"]["POST /api/pick"] = 0.4
    page.locator("#go").click()
    assert page.locator("#mode-two").is_disabled()
    page.locator("#numbers .number-ticket").first.wait_for()
    state["delays"]["POST /api/picks"] = 0.4
    page.locator("#save").click()
    assert page.locator("#mode-two").is_disabled()
    page.wait_for_function("document.getElementById('mode-two').disabled === false")
    state["delays"]["PUT /api/settings"] = 0.4
    page.locator("#notify").evaluate("node => node.closest('details').open = true")
    page.locator("#saveSettings").click()
    assert page.locator("#mode-two").is_disabled()
    page.wait_for_function("document.getElementById('mode-two').disabled === false")


def test_delayed_mode_reads_cannot_overwrite_current_mode(ui):
    page, state = ui
    state["settings_2"].update(draws=8, picks=10)
    state["stats_2"].update(picks=8, exact_hits=2)
    for path in ("settings", "picks", "stats"):
        state["delays"][f"GET /api/{path}?digits=2"] = 0.4
    page.locator("#mode-two").click()
    assert page.locator("#result").is_hidden()
    page.locator("#mode-three").click()
    page.wait_for_function(
        "document.body.dataset.digits === '3' && !document.getElementById('go').disabled"
    )
    page.wait_for_timeout(550)
    assert page.locator("#draws").input_value() == "2"
    assert page.locator("#picks").input_value() == "5"
    assert "เลขท้าย 3 ตัว" in page.locator("#mode-label").inner_text()
    page.get_by_role("button", name="เลขที่บันทึก", exact=True).click()
    assert page.locator("#stat-exact").inner_text() == "0"
    select_mode(page, 2)
    assert page.locator("#draws").input_value() == "8"
    assert page.locator("#picks").input_value() == "10"
    page.wait_for_function("document.getElementById('stat-exact').textContent === '2'")


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_two_digit_layout_and_result_visibility(ui, width):
    page, _ = ui
    page.set_viewport_size({"width": width, "height": 900})
    select_mode(page, 2)
    page.locator("#go").click()
    page.locator("#numbers .number-ticket").first.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert all(
        len(number) == 2
        for number in page.locator("#numbers .number-ticket").all_inner_texts()
    )
    for selector in ["#mode-two", "#mode-three", "#go", "#save", "#copy", "#again"]:
        box = page.locator(selector).bounding_box()
        assert box and box["height"] >= 44 and box["width"] >= 44, (selector, box)
    destination = os.environ.get("LOTTO_UI_SCREENSHOTS")
    if destination:
        Path(destination).mkdir(parents=True, exist_ok=True)
        for theme in ("light", "dark"):
            page.emulate_media(color_scheme=theme)
            page.screenshot(
                path=str(Path(destination) / f"lotto-two-{width}-{theme}.png"),
                full_page=True,
                animations="disabled",
            )
