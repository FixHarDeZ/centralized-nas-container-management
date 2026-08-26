"""The smallest checks that fail if the pipeline's logic breaks.

Run inside the image, where Raqm and the Thai fonts exist:
    docker compose run --rm --entrypoint pytest shorts-factory tests/ -v
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "42")
os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

from app import main, render, script as script_gen, youtube  # noqa: E402


def a_card(text: str = "ทดสอบการ์ด", code: str | None = None) -> dict:
    return {
        "lines": [text],
        "code": code,
        "query": "server room racks",
        "narration": "อ่านออกเสียงประโยคนี้",
    }


def a_script(cards: int = 5) -> dict:
    return {
        "title": "ทดสอบ",
        "description": "คำอธิบาย",
        "hashtags": ["#devops"],
        "cards": [a_card() for _ in range(cards)],
    }


# --- script validation -------------------------------------------------------

def test_valid_script_passes():
    assert script_gen.validate(a_script())["cards"]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda s: s.update(cards=s["cards"][:2]), id="too-few-cards"),
        pytest.param(lambda s: s.update(cards=s["cards"] * 3), id="too-many-cards"),
        pytest.param(lambda s: s.pop("hashtags"), id="missing-field"),
        pytest.param(lambda s: s["cards"][0].update(lines=["ก" * 60]), id="line-absurdly-long"),
        pytest.param(lambda s: s["cards"][0].update(lines=[]), id="no-lines"),
        pytest.param(lambda s: s["cards"][0].update(narration="  "), id="empty-narration"),
        pytest.param(lambda s: s["cards"][0].update(query=""), id="empty-footage-query"),
    ],
)
def test_bad_script_is_rejected(mutate):
    script = a_script()
    mutate(script)
    with pytest.raises(script_gen.ScriptError):
        script_gen.validate(script)


def test_slightly_over_target_line_is_accepted():
    """A line a few characters over target must not fail the whole clip —
    the renderer shrinks it. Only absurd lines are rejected."""
    script = a_script()
    script["cards"][0]["lines"] = ["ก" * (script_gen.TARGET_CHARS_PER_LINE + 1)]
    assert script_gen.validate(script)


def test_hard_max_line_still_fits_the_card():
    longest = "ก" * script_gen.HARD_MAX_CHARS_PER_LINE
    usable = render.CW - render.MARGIN * 2
    font = render._fit([longest], render.THAI_BOLD, render.TEXT_SIZE, usable)
    assert font.getlength(longest) <= usable


def test_prosody_settings_reach_edge_tts(monkeypatch, tmp_path):
    """Rate and pitch must be passed through, not silently dropped."""
    seen = {}

    class FakeCommunicate:
        def __init__(self, text, voice, rate="+0%", pitch="+0Hz"):
            seen.update(text=text, voice=voice, rate=rate, pitch=pitch)

        async def save(self, path):
            pathlib.Path(path).write_bytes(b"")

    monkeypatch.setattr(render.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setenv("TTS_RATE", "+12%")
    monkeypatch.setenv("TTS_PITCH", "-20Hz")
    asyncio.run(render.speak("ทดสอบ", tmp_path / "a.mp3"))

    assert seen["rate"] == "+12%"
    assert seen["pitch"] == "-20Hz"


def test_parse_unwraps_fenced_json():
    assert script_gen._parse('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_rejects_prose():
    with pytest.raises(script_gen.ScriptError):
        script_gen._parse("ไม่มี JSON เลย")


# --- delivery naming ---------------------------------------------------------

def test_slugify_keeps_thai_and_drops_separators():
    assert main.slugify("Docker บน NAS: ทำไม/ช้า?") == "Docker-บน-NAS-ทำไมช้า"


def test_slugify_never_returns_empty():
    assert main.slugify("???") == "clip"


# --- trust boundary ----------------------------------------------------------

def test_updates_from_other_chats_are_dropped():
    # Read the id off the module: this suite also runs against the real .env.
    mine, theirs = main.CHAT_ID, main.CHAT_ID + 1
    assert main.is_ours({"message": {"chat": {"id": mine}, "text": "hi"}})
    assert not main.is_ours({"message": {"chat": {"id": theirs}, "text": "hi"}})
    assert main.is_ours({"callback_query": {"message": {"chat": {"id": mine}}}})
    assert not main.is_ours({"callback_query": {"message": {"chat": {"id": theirs}}}})


# --- drawing (needs Raqm + the Thai font, i.e. the real image) ---------------

def test_card_over_footage_is_transparent_at_frame_size(tmp_path):
    """Over B-roll the card must be an overlay, not an opaque background."""
    from PIL import Image

    path = render.draw_card(a_card(), tmp_path / "o.png", over_footage=True)
    with Image.open(path) as img:
        assert img.size == (render.W, render.H)
        assert img.mode == "RGBA"
        assert img.getpixel((5, 5))[3] == 0  # corner is see-through


def test_footage_is_skipped_without_a_key(monkeypatch):
    from app import footage

    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert not footage.enabled()
    assert asyncio.run(footage.fetch("server room", pathlib.Path("/tmp/none.mp4"))) is None


def test_card_is_drawn_oversized_for_the_zoom():
    from PIL import Image

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = render.draw_card(
            a_card("เก็บไว้ที่ไหน", code="docker ps -a"), pathlib.Path(tmp) / "c.png"
        )
        with Image.open(path) as img:
            # Bigger than the frame: the Ken Burns crop lives in the extra pixels.
            assert img.size == (render.CW, render.CH)
            assert img.size > (render.W, render.H)


def test_long_line_shrinks_to_fit():
    wide = "ตั้งค่าคอนเทนเนอร์ให้ครบทุกอย่าง"
    font = render._fit([wide], render.THAI_BOLD, render.TEXT_SIZE, render.CW - render.MARGIN * 2)
    assert font.getlength(wide) <= render.CW - render.MARGIN * 2


def test_zoom_lands_exactly_on_the_last_frame():
    """The move must finish with the narration, not before or after it."""
    frames = 150
    rate = float(render.ken_burns(frames, True).split("min(1+")[1].split("*on")[0])
    assert 1 + rate * (frames - 1) == pytest.approx(render.OVERSCAN)


def test_zoom_out_starts_wide_and_ends_at_frame_size():
    assert f"max({render.OVERSCAN}-" in render.ken_burns(90, False)


def test_segment_is_frame_sized_silent_and_the_right_length(tmp_path):
    """Segments carry no audio — the narration is muxed over the whole clip.

    A segment that kept its own audio track would make `concat -c copy`
    produce garbage.
    """
    png = render.draw_card(a_card("ทดสอบการซูม"), tmp_path / "c.png")
    out = render._segment(png, 2.0, tmp_path / "s.mp4")

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    assert probe == [f"video,{render.W},{render.H}"]  # one stream, no audio

    seconds = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True).stdout.strip())
    assert seconds == pytest.approx(2.0, abs=0.1)


def test_narration_is_one_take_with_a_start_per_card():
    """One synthesis call for the whole Script, and boundaries that line up."""
    import tempfile

    cards = [
        {"narration": "ปัญหาคือ ด็อกเกอร์ ไม่ได้จำกัดขนาดล็อกให้เรา, มันจะเขียนไปเรื่อยๆ"},
        {"narration": "วิธีแก้ง่ายสุด คือใส่ออปชันตอนรันคอนเทนเนอร์"},
        {"narration": "สรุปคือ ตั้งค่าไว้เสมอ, กันดิสก์เต็มได้ชัวร์"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(render.narrate(cards, pathlib.Path(tmp) / "n.mp3"))
        assert result is not None, "sentence boundaries did not line up"
        audio, starts = result

        assert len(starts) == len(cards)
        assert starts[0] == 0.0
        assert starts == sorted(starts), "card starts must run forward"
        # every cut lands inside the file
        assert starts[-1] < render.audio_seconds(audio)


def test_no_music_folder_means_no_music(monkeypatch, tmp_path):
    monkeypatch.setattr(render, "BGM_DIR", tmp_path / "missing")
    assert render.pick_music() is None


def test_empty_music_folder_means_no_music(monkeypatch, tmp_path):
    monkeypatch.setattr(render, "BGM_DIR", tmp_path)
    (tmp_path / "notes.txt").write_text("not a track")
    assert render.pick_music() is None


def test_music_is_picked_from_the_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(render, "BGM_DIR", tmp_path)
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "b.wav").write_bytes(b"")
    assert render.pick_music().name in {"a.mp3", "b.wav"}


# --- youtube -----------------------------------------------------------------

def test_first_frame_is_a_thumbnail_sized_jpeg(tmp_path):
    """The cover is the opening frame, and small enough for YouTube's 2MB cap."""
    from PIL import Image

    png = render.draw_card(a_card("ปกคลิป"), tmp_path / "c.png")
    clip = render._segment(png, 1.0, tmp_path / "s.mp4")
    cover = render.first_frame(clip, tmp_path / "cover.jpg")

    with Image.open(cover) as img:
        assert img.format == "JPEG"
        assert img.size == (render.W, render.H)
    assert 0 < cover.stat().st_size < 2 * 1024 * 1024


def test_upload_needs_all_three_credentials(monkeypatch):
    for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "x")
    assert youtube.configured()
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "")
    assert not youtube.configured()


def test_upload_refuses_without_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "")
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(youtube.UploadError):
        asyncio.run(youtube.upload(clip, a_script()))


def test_metadata_strips_hashes_into_tags(monkeypatch):
    monkeypatch.setenv("YOUTUBE_PRIVACY", "public")
    script = a_script()
    script["hashtags"] = ["#DevOps", "#AIOps"]
    body = youtube.metadata(script)
    assert body["snippet"]["tags"] == ["DevOps", "AIOps"]
    assert "#DevOps #AIOps" in body["snippet"]["description"]
    assert body["status"]["privacyStatus"] == "public"
    assert body["status"]["selfDeclaredMadeForKids"] is False


def test_metadata_respects_youtube_limits():
    script = a_script()
    script["title"] = "ก" * 300
    script["description"] = "ข" * 9000
    body = youtube.metadata(script)
    assert len(body["snippet"]["title"]) == youtube.MAX_TITLE
    assert len(body["snippet"]["description"]) <= youtube.MAX_DESCRIPTION


def test_internal_full_stop_would_split_a_card():
    assert render._speakable("แบบนี้. แล้วก็แบบนั้น") == "แบบนี้, แล้วก็แบบนั้น"
