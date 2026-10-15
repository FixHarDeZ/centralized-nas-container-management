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


def test_markdown_is_english_with_tag_lock_and_no_narration(monkeypatch):
    fake_model(monkeypatch, [board(3)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    text = storyboard.studio_markdown(result, "@Nong")
    assert not storyboard.THAI.search(text)
    assert "9:16" in text and "8 seconds" in text and "No dialogue" in text
    assert text.count("[SCENE ") == 3
    for block in text.split("[SCENE ")[1:]:
        assert "@Nong" in block and LOCK in block
    assert "CHARACTERS: @Nong — " + LOCK in text


def test_markdown_without_a_character_has_no_tag(monkeypatch):
    plain = board(1, tag="A brass house key on a desk")
    plain["overview"]["master_character"] = None
    fake_model(monkeypatch, [plain])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [1], {1: 1}, choice=storyboard.NONE))
    text = storyboard.studio_markdown(result, "")
    assert "CHARACTERS" not in text and "@" not in text


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
