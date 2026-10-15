import asyncio
import os
import subprocess

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "42")

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from app import footage, render  # noqa: E402


def clip(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True, capture_output=True)
    return path


def tone(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=duration={seconds}", str(path)],
                   check=True, capture_output=True)
    return path


def test_hold_freezes_the_last_frame_instead_of_looping(tmp_path):
    png = tmp_path / "card.png"
    Image.new("RGBA", (render.W, render.H), (0, 0, 0, 0)).save(png)
    out = render._segment_over_footage(png, 3.0, clip(tmp_path / "c.mp4", 1), tmp_path / "s.mp4", hold=True)
    assert render.audio_seconds(out) == pytest.approx(3.0, abs=0.1)


def test_build_reuses_narration_and_labels_studio_footage(tmp_path, monkeypatch):
    async def no_tts(*args, **kwargs):
        raise AssertionError("narration was supplied; TTS must not run")

    async def no_footage(query, dest):
        return None

    monkeypatch.setattr(render, "_narration_track", no_tts)
    monkeypatch.setattr(footage, "fetch", no_footage)
    monkeypatch.setattr(render, "pick_music", lambda: None)
    script = {"title": "t", "cards": [
        {"lines": ["หนึ่ง"], "narration": "หนึ่ง", "spoken": "หนึ่ง", "query": "x"},
        {"lines": ["สอง"], "narration": "สอง", "spoken": "สอง", "query": "y"}]}
    audio = tone(tmp_path / "n.wav", 4)
    seg = clip(tmp_path / "flow.mp4", 1)
    out, details = asyncio.run(render.build(script, tmp_path / "work", supplied={0: seg},
                                            narration=(audio, [0.0, 2.0]), hold={0}))
    assert out.is_file()
    assert details["narration_reused"] is True
    assert details["cards"][0]["footage_source"] == "flow-studio"
    assert details["cards"][1]["footage_source"] is None


def test_build_speaks_afresh_when_the_saved_take_has_another_card_count(tmp_path, monkeypatch):
    spoken = []

    async def tts(cards, workdir, locale):
        spoken.append(len(cards))
        return tone(tmp_path / "fresh.wav", 4), [0.0, 2.0]

    async def no_footage(query, dest):
        return None

    monkeypatch.setattr(render, "_narration_track", tts)
    monkeypatch.setattr(footage, "fetch", no_footage)
    monkeypatch.setattr(render, "pick_music", lambda: None)
    script = {"title": "t", "cards": [
        {"lines": ["หนึ่ง"], "narration": "หนึ่ง", "spoken": "หนึ่ง", "query": "x"},
        {"lines": ["สอง"], "narration": "สอง", "spoken": "สอง", "query": "y"}]}
    stale = (tone(tmp_path / "old.wav", 4), [0.0])
    _, details = asyncio.run(render.build(script, tmp_path / "work", narration=stale))
    assert spoken == [2]
    assert details["narration_reused"] is False
    assert len(details["cards"]) == 2
