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


def test_footage_is_not_dimmed_under_the_card(tmp_path):
    """A frame-wide scrim read as a dim, blurry picture; the outline carries the text."""
    png = tmp_path / "card.png"
    Image.new("RGBA", (render.W, render.H), (0, 0, 0, 0)).save(png)
    src = tmp_path / "white.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=white:size=720x1280:rate=24:duration=1",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True, capture_output=True)
    out = render._segment_over_footage(png, 1.0, src, tmp_path / "s.mp4")
    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-i", str(out), "-frames:v", "1", str(frame)], check=True, capture_output=True)
    with Image.open(frame) as img:
        assert min(img.convert("RGB").getpixel((render.W // 2, 50))) > 235


def test_a_speaking_cards_caption_sits_under_the_face(tmp_path):
    card = {"lines": ["อายุ 30 40 แล้ว", "ยังไม่ได้เริ่มลงทุน", "คิดว่าสายไปแล้วใช่ไหม", "คำตอบคือ ยังไม่สาย"]}

    def ink_rows(**kw):
        path = render.draw_card(card, tmp_path / "c.png", over_footage=True, **kw)
        with Image.open(path) as img:
            box = img.getchannel("A").getbbox()
        return box

    centred, low = ink_rows(), ink_rows(low=True)
    # Clear of the mouth (~44% of the height) and of the Shorts title band.
    assert low[1] > render.H * 0.5 and low[3] <= render.LOW_BOTTOM + 10
    assert centred[1] < render.H * 0.44
    # Narrow enough to clear the right-hand buttons.
    assert low[2] - low[0] <= render.LOW_WIDTH


def test_the_caption_over_footage_has_a_dark_outline(tmp_path):
    path = render.draw_card({"lines": ["ทดสอบ"]}, tmp_path / "c.png", over_footage=True)
    with Image.open(path) as img:
        colours = {px[:3] for _, px in img.getcolors(1 << 24) if px[3] == 255}
    assert (0, 0, 0) in colours and render.FG in colours


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
