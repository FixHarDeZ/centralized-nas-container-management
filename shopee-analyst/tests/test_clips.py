import json
import threading
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from app import analyst, clips, main, notify

NOW = datetime(2026, 11, 2, 23, 0, tzinfo=UTC)  # 06:00 Bangkok, 3 Nov
CFG = json.loads(analyst.CONFIG_PATH.read_text())["youtube"]


def video(vid, views, title="ป้ายยา หม้อทอดไร้น้ำมัน ใช้ดีมาก", hours_old=10, tags=None):
    return {
        "id": vid,
        "snippet": {
            "title": title,
            "description": "",
            "tags": tags or [],
            "channelTitle": "ช่องทดสอบ",
            "publishedAt": (NOW - timedelta(hours=hours_old)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        },
        "statistics": {"viewCount": str(views)},
    }


class FakeGoogle(BaseHTTPRequestHandler):
    videos: ClassVar[dict] = {}
    search_ids: ClassVar[list] = []
    calls: ClassVar[list] = []

    def log_message(self, *args):
        pass

    def reply(self, body):
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        FakeGoogle.calls.append("token")
        self.reply({"access_token": "AT"})

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(url.query))
        assert self.headers["Authorization"] == "Bearer AT"
        if url.path.endswith("/search"):
            FakeGoogle.calls.append("search")
            self.reply(
                {
                    "items": [
                        {
                            "id": {"videoId": v},
                            "snippet": {
                                "publishedAt": FakeGoogle.videos[v]["snippet"][
                                    "publishedAt"
                                ]
                            },
                        }
                        for v in FakeGoogle.search_ids
                    ]
                }
            )
        else:
            FakeGoogle.calls.append("videos")
            ids = params["id"].split(",")
            self.reply(
                {"items": [FakeGoogle.videos[i] for i in ids if i in FakeGoogle.videos]}
            )


@pytest.fixture(scope="module")
def google():
    server = HTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def telegram(monkeypatch):
    sent = []

    def post(url, payload, headers, timeout):
        sent.append(payload["text"])
        return 200

    monkeypatch.setattr(notify, "_urllib_post", post)
    return sent


@pytest.fixture
def env(monkeypatch, tmp_path, google):
    for name in clips.ENV:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("GOOGLE_TOKEN_URL", f"{google}/token")
    monkeypatch.setenv("YOUTUBE_API_URL", google)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("SHOPEE_APP_ID", raising=False)
    FakeGoogle.calls = []
    FakeGoogle.videos = {}
    FakeGoogle.search_ids = []
    return tmp_path


def test_thai_ratio_drops_foreign_clips():
    assert clips.thai_ratio("O multi tool mais top da SHOPEE #edc") == 0
    assert clips.thai_ratio("#ของใช้ในบ้าน #รีวิว #shopee #garden") > 0.4


def test_search_runs_once_per_day_then_only_views(env, telegram):
    FakeGoogle.videos = {"a": video("a", 5000)}
    FakeGoogle.search_ids = ["a"]
    clips.run(NOW)
    assert FakeGoogle.calls.count("search") == CFG["max_keywords"]

    FakeGoogle.calls = []
    clips.run(NOW + timedelta(hours=6))  # 12:00 same Bangkok day
    assert FakeGoogle.calls.count("search") == 0
    assert FakeGoogle.calls.count("videos") == 1


def test_keyword_cap(env, telegram, tmp_path):
    cfg = json.loads(analyst.CONFIG_PATH.read_text())
    cfg["youtube"]["keywords"] = [f"k{i}" for i in range(10)]
    cfg["youtube"]["max_keywords"] = 2
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    clips.run(NOW, config_path=path)
    assert FakeGoogle.calls.count("search") == 2


def test_momentum_beats_lifetime_after_baseline(env, telegram):
    FakeGoogle.videos = {
        "old": video("old", 90000, hours_old=100),
        "new": video("new", 2000, hours_old=5),
    }
    FakeGoogle.search_ids = ["old", "new"]
    clips.run(NOW)
    assert "ยังไม่มีรอบก่อนให้เทียบ" in telegram[0]

    telegram.clear()
    FakeGoogle.videos["old"]["statistics"]["viewCount"] = "90100"  # +100 in 24h
    FakeGoogle.videos["new"]["statistics"]["viewCount"] = "6800"  # +4800 in 24h
    clips.run(NOW + timedelta(hours=24))
    text = telegram[0]
    assert "ยังไม่มีรอบก่อนให้เทียบ" not in text
    assert "วิวเพิ่ม 200/ชม." in text


def test_foreign_and_small_clips_filtered(env, telegram):
    FakeGoogle.videos = {
        "br": video("br", 80000, title="O multi tool mais top da SHOPEE #edc"),
        "tiny": video("tiny", 50),
        "th": video("th", 3000),
    }
    FakeGoogle.search_ids = ["br", "tiny", "th"]
    assert clips.run(NOW) == 1
    assert "youtu.be/th" in telegram[0]
    assert "youtu.be/br" not in telegram[0]


def test_grounding_drops_invented_products(env, telegram, monkeypatch):
    FakeGoogle.videos = {
        "a": video("a", 5000, title="ป้ายยา หม้อทอดไร้น้ำมัน ใช้ดีมาก"),
        "b": video("b", 4000, title="ของดีบอกต่อ #ของใช้ในบ้าน"),
    }
    FakeGoogle.search_ids = ["a", "b"]
    monkeypatch.setenv("MIMO_API_KEY", "k")
    answer = json.dumps(
        [
            {"id": "a", "product": "หม้อทอด ไร้น้ำมัน", "angle": "ทอดไก่ให้ดู"},
            {"id": "b", "product": "เครื่องดูดฝุ่นไร้สาย", "angle": "แต่งขึ้นเอง"},
        ],
        ensure_ascii=False,
    )

    async def fake_ask(text, within):
        return "```json\n" + answer + "\n```"

    monkeypatch.setattr(clips, "_ask", fake_ask)
    assert clips.run(NOW) == 1
    text = telegram[0]
    assert "หม้อทอด ไร้น้ำมัน" in text
    assert "shopee.co.th/search?keyword=" in text
    assert "เครื่องดูดฝุ่น" not in text
    assert "youtu.be/b" not in text


def test_mimo_failure_sends_raw_list(env, telegram, monkeypatch):
    FakeGoogle.videos = {"a": video("a", 5000)}
    FakeGoogle.search_ids = ["a"]
    monkeypatch.setenv("MIMO_API_KEY", "k")

    async def stall(text, within):
        raise TimeoutError("silent")

    monkeypatch.setattr(clips, "_ask", stall)
    assert clips.run(NOW) == 1
    assert "ส่งรายการคลิปดิบ" in telegram[0]
    assert "youtu.be/a" in telegram[0]


def test_pool_saved_even_when_delivery_fails(env, monkeypatch):
    FakeGoogle.videos = {"a": video("a", 5000)}
    FakeGoogle.search_ids = ["a"]
    monkeypatch.setattr(notify, "_urllib_post", lambda *a: 400)
    with pytest.raises(RuntimeError):
        clips.run(NOW)
    assert analyst.load_json(env / "youtube" / "pool.json", {})["ids"] == {
        "a": FakeGoogle.videos["a"]["snippet"]["publishedAt"]
    }
    assert not list((env / "youtube" / "snapshots").glob("*.json"))


def test_quota_error_is_reported_without_token(env, telegram, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("YouTube API HTTP 403 quotaExceeded")

    monkeypatch.setattr(clips.Api, "get", boom)
    assert main.run_once() == 1
    assert "quotaExceeded" in telegram[0]
    assert "TOKEN" not in telegram[0]


def test_html_escaped(env, telegram):
    FakeGoogle.videos = {"a": video("a", 5000, title="ป้ายยา <b>ของดี</b> & ถูก")}
    FakeGoogle.search_ids = ["a"]
    clips.run(NOW)
    assert "&lt;b&gt;ของดี&lt;/b&gt; &amp; ถูก" in telegram[0]
