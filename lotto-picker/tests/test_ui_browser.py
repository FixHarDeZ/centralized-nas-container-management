"""Opt-in browser acceptance tests; fixture server never contacts GLO or Telegram."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def handle_request(self):
            key = f"{self.command} {self.path}"
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", 0))) or "null"
            )
            state["requests"].append((key, body))
            time.sleep(state["delays"].get(key, 0))
            if state["failures"].get(key, 0):
                state["failures"][key] -= 1
                return self.reply({"detail": "Temporary failure"}, 503)
            if self.path == "/api/settings":
                if self.command == "PUT":
                    state["settings"] = body
                return self.reply(state["settings"])
            if self.path == "/api/draws":
                return self.reply(state["draws"])
            if self.path == "/api/stats":
                return self.reply(state["stats"])
            if self.path == "/api/pick":
                return self.reply(
                    {
                        "numbers": state["numbers"],
                        "settings": body,
                        "excluded": ["001", "002"],
                        "excluded_count": 2,
                        "pool_size": 998 if state["numbers"] else 0,
                        "draws_used": ["2026-10-01"],
                    }
                )
            if self.path == "/api/picks":
                if self.command == "POST":
                    state["picks"].insert(
                        0,
                        {
                            "id": 1,
                            "numbers": body["numbers"],
                            "settings": body["settings"],
                            "source": "manual",
                            "created_at": "2026-10-16 09:00:00",
                            "based_on": "2026-10-01",
                            "result_draw": None,
                            "result": None,
                        },
                    )
                    return self.reply({"id": 1}, 201)
                return self.reply(state["picks"])
            if self.path.startswith("/api/picks/") and self.command == "DELETE":
                state["picks"] = []
                return self.reply(None, 204)
            if self.path == "/api/sync":
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
