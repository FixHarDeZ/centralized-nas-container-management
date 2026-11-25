"""reels.py against a fake Graph API (no network) + clipjob.py's `reel` command gates.

Run: uv run --with pytest pytest -q hermes-agent/skills/shopee-clip/scripts/test_reels.py
"""
import io
import json
import os
import sys
import urllib.error
import urllib.parse

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reels  # noqa: E402

TOKEN = "EAAG-secret-token"


class FakeGraph:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def __call__(self, req, timeout=None):
        body = req.data
        form = dict(urllib.parse.parse_qsl(body.decode())) if body and req.full_url.endswith("video_reels") else {}
        self.calls.append({"url": req.full_url, "headers": {k.lower(): v for k, v in req.header_items()},
                           "form": form, "size": len(body or b"")})
        phase = form.get("upload_phase")
        if self.fail_at and self.fail_at == (phase or ("upload" if "rupload" in req.full_url else "status")):
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(json.dumps(
                {"error": {"type": "OAuthException", "code": 200, "message": "Permissions error"}}).encode()))
        if phase == "start":
            out = {"video_id": "123", "upload_url": "https://rupload.facebook.com/video-upload/v27.0/123"}
        elif "rupload" in req.full_url or phase == "finish":
            out = {"success": True}
        else:
            out = {"status": {"video_status": "ready"}}
        return io.BytesIO(json.dumps(out).encode())


@pytest.fixture
def clip(tmp_path):
    p = tmp_path / "final.mp4"
    p.write_bytes(b"\0" * 2048)
    return str(p)


def test_draft_runs_start_upload_finish_with_the_ai_label(clip):
    g = FakeGraph()
    r = reels.draft(clip, "กระเป๋าวิ่ง\n\n#ของดีบอกต่อ", "999", TOKEN, opener=g, sleep=lambda s: None)
    assert r == {"video_id": "123", "state": "DRAFT", "status": {"video_status": "ready"}}
    start, up, fin, st = g.calls
    assert start["url"].endswith("/v27.0/999/video_reels") and start["form"]["upload_phase"] == "start"
    assert up["url"].startswith("https://rupload.facebook.com/") and up["size"] == 2048
    assert up["headers"]["authorization"] == f"OAuth {TOKEN}" and up["headers"]["file_size"] == "2048"
    assert fin["form"]["video_state"] == "DRAFT" and fin["form"]["is_ai_generated"] == "true"
    assert fin["form"]["description"].endswith("#ของดีบอกต่อ")
    assert all(TOKEN not in c["url"] for c in g.calls)          # the token never rides in a URL


def test_graph_error_names_the_step_reason(clip):
    with pytest.raises(reels.GraphError, match="Permissions error"):
        reels.draft(clip, "x", "999", TOKEN, opener=FakeGraph(fail_at="finish"), sleep=lambda s: None)


def test_description_joins_caption_and_hashtags():
    assert reels.description_for("ใส่วิ่งไม่เด้ง", " #วิ่ง #ShopeeTH ") == "ใส่วิ่งไม่เด้ง\n\n#วิ่ง #ShopeeTH"
    assert reels.description_for("", "#a") == "#a"


def test_cli_without_env_says_so(clip, monkeypatch, capsys):
    monkeypatch.delenv("FB_PAGE_ID", raising=False)
    monkeypatch.delenv("FB_PAGE_TOKEN", raising=False)
    assert reels.main(["draft", clip]) == 2
    assert "not set" in capsys.readouterr().out


# ---- clipjob reel
import importlib.util  # noqa: E402
import tempfile  # noqa: E402

spec = importlib.util.spec_from_file_location("clipjob_reel", os.path.join(HERE, "clipjob.py"))
cj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cj)
cj.DIR = tempfile.mkdtemp(prefix="clipjob-reel-")


def delivered(file):
    j = cj.new_job("r-1", "presenter", "Bag", "https://s.shopee.co.th/x", 1, ["/tmp/ref.jpg"], character="น้องคอรัล")
    j["status"] = "delivered"
    j["delivery"] = {"mirror": {"file": file, "caption": "กระเป๋าวิ่ง", "hashtags": "#วิ่ง"}}
    return j


def test_reel_needs_the_page_env(clip, monkeypatch):
    monkeypatch.delenv("FB_PAGE_ID", raising=False)
    with pytest.raises(cj.Refused, match="FB_PAGE_ID"):
        cj.cmd_reel(delivered(clip))


def test_reel_refuses_an_open_job(clip):
    j = delivered(clip)
    j["status"] = "open"
    with pytest.raises(cj.Refused, match="not delivered"):
        cj.cmd_reel(j)


def test_reel_uploads_once_then_needs_again(clip, monkeypatch):
    monkeypatch.setenv("FB_PAGE_ID", "999")
    monkeypatch.setenv("FB_PAGE_TOKEN", TOKEN)
    sent = []
    monkeypatch.setattr(reels, "draft", lambda f, d, p, t: sent.append((f, d)) or
                        {"video_id": "123", "state": "DRAFT", "status": {}})
    j = delivered(clip)
    out = cj.cmd_reel(j)
    assert out["reel"]["video_id"] == "123" and sent == [(clip, "กระเป๋าวิ่ง\n\n#วิ่ง")]
    assert "already" in cj.cmd_reel(j)["note"] and len(sent) == 1
    cj.cmd_reel(j, again=True)
    assert len(sent) == 2
