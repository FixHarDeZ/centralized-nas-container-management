import asyncio
import json
import os

os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

import pytest  # noqa: E402

from app import storyboard  # noqa: E402

LOCK = "the same 28-year-old Thai woman with a short black bob and round glasses"
SCRIPT = {"title": "ดอกเบี้ย 2.60%", "cards": [
    {"lines": ["ดอกเบี้ย 2.60%"], "narration": "สินเชื่อบ้านดอกเบี้ย", "query": "house key"},
    {"lines": ["ธอส."], "narration": "โครงการนี้คือ", "query": "bank"},
    {"lines": ["สรุป"], "narration": "สรุปนะ", "query": "couple"}]}


def board(n, tag=LOCK):
    return {"overview": {"title": "ชื่อ", "mood_tone_progression": "อุ่น", "target_audience": "คนทำงาน",
                         "master_character": {"name": "Nong", "age": 28, "ethnicity": "Thai",
                                              "appearance": "bob", "outfit": "linen",
                                              "locked_prompt_tag": "anything the model wrote"}},
            "scenes": [{"scene_number": i + 1, "camera": "กล้อง", "scene_description": "ฉาก",
                        "visual_details": "รายละเอียด", "scene_mood_note": "อารมณ์",
                        "sound_verbatim": "", "on_screen_text": "",
                        "image_gen_prompt": f"{tag} holds a key, 9:16, no text, no watermark, no UI, no split-screen",
                        "motion": "slow push in"} for i in range(n)]}


def fake_model(monkeypatch, replies):
    calls = []

    async def say(client, messages, temperature, budget):
        calls.append(messages)
        return json.dumps(replies.pop(0))

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    return calls


def test_for_studio_pins_the_tag_and_maps_shots_to_cards(monkeypatch):
    calls = fake_model(monkeypatch, [board(3)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    assert [s["card"] for s in result["scenes"]] == [0, 2, 2]
    assert result["scenes"][1]["sound_verbatim"] == "สรุปนะ"
    assert result["overview"]["master_character"]["locked_prompt_tag"] == LOCK
    brief = calls[0][1]["content"]
    assert "2 shot" in brief and "ธอส." not in brief


def test_a_board_with_the_wrong_shot_count_is_retried(monkeypatch):
    calls = fake_model(monkeypatch, [board(2), board(3)])
    asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                      choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    assert len(calls) == 2 and "3" in calls[1][-1]["content"]


def test_markdown_is_the_short_studio_shape(monkeypatch):
    fake_model(monkeypatch, [board(3)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    result["overview"]["title_en"] = "Home Loan Math"
    text = storyboard.studio_markdown(result, "@Nong")
    assert not storyboard.THAI.search(text)
    assert text.startswith("Story Title: Home Loan Math\n\nCharacters:\n"
                           "@Nong is a 28-year-old Thai woman with a short black bob and round glasses.\n")
    assert text.count("Scene ") == 3 and text.count("Dialogue: none.") == 3
    for block in text.split("Scene ")[1:]:
        assert "@Nong holds a key." in block and LOCK not in block and "9:16" not in block
    assert "no watermark" not in text and "seconds" not in text


def test_a_thai_or_missing_title_is_left_out(monkeypatch):
    fake_model(monkeypatch, [board(1)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [1], {1: 1},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    assert storyboard.studio_markdown(result, "@Nong").startswith("Characters:")
    result["overview"]["title_en"] = "ดอกเบี้ย"
    assert storyboard.studio_markdown(result, "@Nong").startswith("Characters:")


def test_speaking_markdown_carries_the_voice_and_each_line(monkeypatch):
    fake_model(monkeypatch, [board(2)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [0, 1], {0: 1, 1: 1},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    text = storyboard.studio_markdown(result, "@Nong", {"language": "Thai"})
    assert "@Nong speaks in a warm, clear, medium-pitch voice, fluent native Thai" in text
    assert 'Dialogue: "สินเชื่อบ้านดอกเบี้ย"' in text and 'Dialogue: "โครงการนี้คือ"' in text


# The scene-1 prompt of live pack 20261020-122900-391.
LIVE = ("Photorealistic vertical 9:16 frame of the same 28-year-old Korean woman with long "
        "straight dark hair, fair skin, a cute and cheerful face, small silver stud earrings, and a "
        "soft mint green cardigan over a white blouse, standing in a bright minimalist bathroom "
        "looking into a rounded wall mirror and speaking directly to camera with a curious, honest "
        "expression, skincare bottles softly blurred on a stone shelf behind her, warm soft vanity "
        "lighting, clean modern tile, natural skin texture, shallow depth of field, clean center "
        "composition for text overlay, no text, no watermark, no UI, no split-screen")
LIVE_LOCK = ("the same 28-year-old Korean woman with long straight dark hair, fair skin, a cute and "
             "cheerful face, small silver stud earrings, and a soft mint green cardigan over a white blouse")


def test_scene_text_cuts_a_real_prompt_to_one_sentence():
    assert storyboard.scene_text(LIVE, LIVE_LOCK, "@Minjee") == (
        "@Minjee standing in a bright minimalist bathroom looking into a rounded wall mirror and "
        "speaking directly to camera with a curious, honest expression, skincare bottles softly "
        "blurred on a stone shelf behind her, warm soft vanity lighting, clean modern tile, natural "
        "skin texture, shallow depth of field.")
    close = LIVE.replace("9:16 frame of", "9:16 close-up frame of")
    assert storyboard.scene_text(close, LIVE_LOCK, "@Minjee").startswith("Close-up frame of @Minjee standing")
    shot = LIVE.replace("9:16 frame of", "9:16 shot of")
    assert storyboard.scene_text(shot, LIVE_LOCK, "@Minjee").startswith("@Minjee standing")
    assert storyboard.character_line("@Minjee", LIVE_LOCK).startswith(
        "@Minjee is a 28-year-old Korean woman with long straight dark hair")


def test_markdown_without_a_character_has_no_tag(monkeypatch):
    plain = board(1, tag="A brass house key on a desk")
    plain["overview"]["master_character"] = None
    fake_model(monkeypatch, [plain])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [1], {1: 1}, choice=storyboard.NONE))
    text = storyboard.studio_markdown(result, "")
    assert "Characters" not in text and "@" not in text and "Scene 1:\nBrass house key on a desk holds a key.\n" in text


def test_english_character_rejects_thai(monkeypatch):
    replies = ["ผู้หญิง", "the same 30-year-old Thai man with a buzz cut"]

    async def say(client, messages, temperature, budget):
        return replies.pop(0)

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    assert asyncio.run(storyboard.english_character("ผู้ชายไทย 30 ปี")).startswith("the same 30")


def test_portrait_prompt():
    text = storyboard.portrait_prompt(LOCK)
    assert LOCK in text and "9:16" in text and "no text" in text
