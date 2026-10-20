import asyncio
import json
import os

os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

import pytest
from app import script, studio

CARDS = [
    {"lines": ["ดื่มน้ำ"], "narration": "ดื่มน้ำวันละ 8 แก้ว หรือประมาณสองลิตรต่อวัน ผิวจะอิ่มฟู",
     "spoken": "ดื่มน้ำวันละแปดแก้ว หรือประมาณสองลิตรต่อวัน ผิวจะอิ่มฟู"},
    {"lines": ["กันแดด"], "narration": "ทากันแดดทุกวัน", "spoken": "ทากันแดดทุกวัน"},
]


def replies(monkeypatch, answers):
    calls = []

    async def say(client, messages, temperature, budget):
        calls.append(messages)
        return json.dumps(answers.pop(0), ensure_ascii=False)

    monkeypatch.setattr(script, "_say", say)
    monkeypatch.setattr(script, "_client", lambda: None)
    return calls


def test_speech_budget_scales_the_line_to_what_a_10s_shot_holds():
    # 150 characters spoken in 12.9s; a 10s shot holds 7.875s of take.
    assert studio.speech_budget(150, 12.9) == 84
    assert not studio.speak_too_long(studio.SPEAK_FIT) and studio.speak_too_long(7.9)


def test_speech_units_count_thai_characters_and_english_words():
    assert script.speech_units("ดื่ม น้ำ") == 7
    assert script.speech_units("drink more water", "en") == 3


def test_condense_returns_the_shorter_lines(monkeypatch):
    calls = replies(monkeypatch, [{"cards": [
        {"card": 1, "narration": "ดื่มน้ำวันละ 8 แก้ว ผิวจะอิ่มฟู", "spoken": "ดื่มน้ำวันละแปดแก้ว ผิวจะอิ่มฟู"}]}])
    out = asyncio.run(script.condense(CARDS, {0: 30}, "th"))
    assert out == {0: {"narration": "ดื่มน้ำวันละ 8 แก้ว ผิวจะอิ่มฟู",
                       "spoken": "ดื่มน้ำวันละแปดแก้ว ผิวจะอิ่มฟู"}}
    asked = json.loads(calls[0][1]["content"])["cards"]
    assert asked == [{"card": 1, "narration": CARDS[0]["narration"], "spoken": CARDS[0]["spoken"],
                      "lines": ["ดื่มน้ำ"], "max": 30}]


def test_condense_refuses_a_long_line_a_new_number_or_latin_then_retries(monkeypatch):
    calls = replies(monkeypatch, [
        {"cards": [{"card": 1, "narration": "ดื่มน้ำวันละ 12 แก้ว", "spoken": "ดื่ม water วันละสิบสองแก้ว ผิวจะอิ่มฟูมากๆ"}]},
        {"cards": [{"card": 1, "narration": "ดื่มน้ำวันละ 8 แก้ว", "spoken": "ดื่มน้ำวันละแปดแก้ว"}]}])
    out = asyncio.run(script.condense(CARDS, {0: 20}, "th"))
    assert out[0]["spoken"] == "ดื่มน้ำวันละแปดแก้ว"
    feedback = calls[1][-1]["content"]
    assert "เกิน max 20" in feedback and "'12'" in feedback and "water" in feedback


def test_condense_gives_up_after_two_bad_answers(monkeypatch):
    bad = {"cards": [{"card": 1, "narration": "ยาว", "spoken": "ยาวมากเกินไปจริงๆ นะ"}]}
    replies(monkeypatch, [bad, bad])
    with pytest.raises(script.ScriptError, match="ย่อบทพูดไม่สำเร็จ"):
        asyncio.run(script.condense(CARDS, {0: 3}, "th"))


def test_a_silent_model_is_a_script_error_not_a_timeout(monkeypatch):
    async def silent(client, messages, temperature, budget):
        raise TimeoutError("mimo silent for 600s")

    monkeypatch.setattr(script, "_say", silent)
    monkeypatch.setattr(script, "_client", lambda: None)
    with pytest.raises(script.ScriptError, match="โมเดลเงียบ"):
        asyncio.run(script.condense(CARDS, {0: 20}, "th"))
