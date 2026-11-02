import hashlib
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from app import analyst, main, notify

NOW = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)
CONFIG = json.loads(analyst.CONFIG_PATH.read_text())


def node(item_id, sales, name=None, rating=4.8, rate=0.1, price=200):
    return {
        "itemId": item_id,
        "productName": name or f"สินค้า {item_id}",
        "shopName": "ร้านทดสอบ",
        "sales": sales,
        "priceMin": str(price),
        "priceMax": str(price),
        "commissionRate": str(rate),
        "commission": str(price * rate),
        "ratingStar": str(rating),
        "offerLink": f"https://s.shopee.co.th/{item_id}?a=1&b=2",
    }


class FakeShopee(BaseHTTPRequestHandler):
    nodes: ClassVar[list] = []
    signature_ok: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        match = re.fullmatch(
            r"SHA256 Credential=(\w+), Timestamp=(\d+), Signature=(\w+)",
            self.headers["Authorization"],
        )
        expected = hashlib.sha256(
            f"app{match[2]}{raw.decode()}secret".encode()
        ).hexdigest()
        FakeShopee.signature_ok.append(match[3] == expected)
        body = {
            "data": {
                "productOfferV2": {
                    "nodes": FakeShopee.nodes,
                    "pageInfo": {"hasNextPage": False},
                }
            }
        }
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture(scope="module")
def shopee_url():
    server = HTTPServer(("127.0.0.1", 0), FakeShopee)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/graphql"
    server.shutdown()


@pytest.fixture
def telegram(monkeypatch):
    """Captured sendMessage payloads; set telegram.status to fail delivery."""

    class Box:
        def __init__(self):
            self.messages = []
            self.status = 200

    box = Box()

    def post(url, payload, headers, timeout):
        assert url == "https://api.telegram.org/botTOKEN/sendMessage"
        if box.status == 200:
            box.messages.append(payload)
        return box.status

    monkeypatch.setattr(notify, "_urllib_post", post)
    return box


@pytest.fixture
def env(monkeypatch, tmp_path, shopee_url):
    monkeypatch.setenv("SHOPEE_APP_ID", "app")
    monkeypatch.setenv("SHOPEE_APP_SECRET", "secret")
    monkeypatch.setenv("SHOPEE_API_URL", shopee_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    FakeShopee.signature_ok = []
    return tmp_path / "data"


def test_first_run_warns_then_second_run_uses_real_momentum(env, telegram):
    FakeShopee.nodes = [node(1, 10000), node(2, 100), node(3, 900, rating=3.0)]
    analyst.run(NOW)
    first = telegram.messages[0]["text"]
    assert "ข้อมูลยังไม่พอ" in first
    assert "สินค้า 3" not in first
    assert FakeShopee.signature_ok and all(FakeShopee.signature_ok)
    assert telegram.messages[0]["parse_mode"] == "HTML"

    telegram.messages.clear()
    FakeShopee.nodes = [node(1, 10010), node(2, 300), node(4, 80)]
    analyst.run(NOW + timedelta(hours=24))
    second = telegram.messages[0]["text"]
    assert "ข้อมูลยังไม่พอ" not in second
    assert "ขายเพิ่มประมาณ 200 ชิ้น/วัน" in second


def test_recent_pick_is_replaced_by_fresh_product():
    ranked = [{"item_id": str(i)} for i in range(1, 8)]
    picks = analyst.select_fresh(ranked, {"1": NOW.isoformat()}, NOW, CONFIG)
    assert [p["item_id"] for p in picks] == ["2", "3", "4", "5", "6"]


def test_html_is_escaped(env, telegram):
    FakeShopee.nodes = [node(5, 500, name="A<b>&C")]
    analyst.run(NOW)
    text = telegram.messages[0]["text"]
    assert "A&lt;b&gt;&amp;C" in text
    assert "a=1&amp;b=2" in text


def test_failed_delivery_does_not_save_history(env, telegram):
    FakeShopee.nodes = [node(6, 500)]
    telegram.status = 400
    with pytest.raises(RuntimeError) as caught:
        analyst.run(NOW)
    assert "TOKEN" not in str(caught.value)
    assert not list((env / "snapshots").glob("*.json"))


def test_long_output_is_split():
    picks = [
        {**analyst.normalize(node(i, 100, name="ก" * 90)), "sales_per_day": 5.0}
        for i in range(60)
    ]
    messages = analyst.build_messages(picks, NOW, True)
    assert len(messages) > 1
    assert all(len(m) <= analyst.TELEGRAM_LIMIT for m in messages)


def test_baseline_prefers_about_a_day_old(tmp_path):
    for hours in (6, 24, 72):
        stamp = NOW - timedelta(hours=hours)
        (tmp_path / f"{stamp:%Y%m%dT%H%M%SZ}.json").write_text("{}")
    chosen = analyst.choose_baseline(tmp_path, NOW)
    assert analyst.parse_snapshot_time(chosen) == NOW - timedelta(hours=24)


def test_missing_shopee_keys_skip_silently(monkeypatch, telegram, tmp_path):
    monkeypatch.delenv("SHOPEE_APP_ID", raising=False)
    monkeypatch.delenv("SHOPEE_APP_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main.run_once() == 0
    assert telegram.messages == []


def test_api_failure_is_reported(env, telegram, monkeypatch):
    def boom(config):
        raise RuntimeError("Shopee API ตอบ error: error [10035]: no access")

    monkeypatch.setattr(analyst, "fetch_products", boom)
    assert main.run_once() == 1
    assert "10035" in telegram.messages[0]["text"]


def test_probe_returns_first_node(env):
    FakeShopee.nodes = [node(7, 10)]
    result = analyst.probe()
    assert result["nodes"][0]["itemId"] == 7
    assert all(FakeShopee.signature_ok)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (5, 59, (2, 6, 0)),
        (6, 0, (2, 12, 0)),
        (13, 30, (2, 16, 0)),
        (16, 0, (3, 6, 0)),
    ],
)
def test_next_slot(hour, minute, expected):
    now = datetime(2026, 11, 2, hour, minute, tzinfo=analyst.BANGKOK)
    due = main.next_slot(now, [(6, 0), (12, 0), (16, 0)])
    assert (due.day, due.hour, due.minute) == expected


def test_slots_env(monkeypatch):
    monkeypatch.setenv("SLOTS", "16:00, 06:00,12:30")
    assert main.slots() == [(6, 0), (12, 30), (16, 0)]
