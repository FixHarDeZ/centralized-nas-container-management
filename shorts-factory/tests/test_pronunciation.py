"""A checklist points to words in this Script, without claiming to hear them."""
import importlib
import importlib.util

import pytest


def module():
    assert importlib.util.find_spec("app.pronunciation"), "pronunciation checklist is missing"
    return importlib.import_module("app.pronunciation")


def card(narration, spoken, checks=None):
    result = {"narration": narration, "spoken": spoken}
    if checks is not None:
        result["pronunciation_checks"] = checks
    return result


def script(*cards):
    return {"title": "ตรวจคำอ่าน", "cards": list(cards)}


def check(term, spoken, kind="loanword"):
    return {"term": term, "spoken": spoken, "kind": kind}


def test_thai_transliterations_and_multiword_names_are_kept_from_metadata():
    draft = script(card("เปิดด็อกเกอร์แล้วดู Google Flow", "เปิดด็อกเกอร์แล้วดูกูเกิลโฟลว์", [
        check("ด็อกเกอร์", "ด็อกเกอร์"), check("Google Flow", "กูเกิลโฟลว์", "proper_name"),
    ]))
    found = module().collect(draft)
    assert [(c["term"], c["spoken"]) for c in found] == [
        ("Google Flow", "กูเกิลโฟลว์"), ("ด็อกเกอร์", "ด็อกเกอร์"),
    ]


def test_repeats_merge_cards_but_different_readings_stay_visible():
    draft = script(
        card("CPU กับ cpu", "ซีพียู", [check("CPU", "ซีพียู", "acronym")]),
        card("cpu", "ซีพียู", [check("cpu", "ซีพียู", "acronym")]),
        card("CPU", "ซีพีอยู่", [check("CPU", "ซีพีอยู่", "acronym")]),
    )
    found = module().collect(draft)
    assert len(found) == 2
    assert found[0]["cards"] == [1, 2]
    assert found[1]["cards"] == [3]


@pytest.mark.parametrize("bad", [None, "bad", {}, 42, [None, "bad", {}]])
def test_invalid_metadata_does_not_lose_legacy_fallback(bad):
    draft = script(card("ใช้ CPU", "ใช้ซีพียู", bad))
    assert module().normalize(draft)["cards"]
    found = module().collect(draft)
    assert [c["term"] for c in found] == ["CPU"]
    assert found[0]["spoken"] == "", "do not invent a mapping"
    assert found[0]["contexts"][1] == "ใช้ซีพียู"


def test_invented_terms_and_unverified_readings_are_removed_without_rejecting_script():
    draft = script(card("RAID เปิด Docker", "เรดเปิดด็อกเกอร์", [
        check("Netflix", "เน็ตฟลิกซ์"), check("Docker", "ผิด"),
        check("AI", "เรด", "acronym"), check("RAID", "เรด", "unknown"),
    ]))
    assert module().normalize(draft)["cards"][0]["pronunciation_checks"] == []
    assert {c["term"] for c in module().collect(draft)} == {"RAID", "Docker"}


def test_fallback_preserves_dotted_initials_and_model_names_and_ignores_unsaid_text():
    first = card("ใช้ A.I. กับ GPT-4 และ F-35", "ใช้เอไอกับจีพีทีโฟร์และเอฟสามสิบห้า")
    first.update(lines=["Netflix"], query="Google Flow", code="docker ps")
    draft = script(first)
    draft.update(description="Disney", hashtags=["#YouTube"])
    assert {c["term"] for c in module().collect(draft)} == {"A.I.", "GPT-4", "F-35"}


def test_english_fallback_does_not_flag_every_english_word():
    draft = script(card("Use Docker with CPU and GPT-4.", "Use Docker with C P U and GPT four."))
    assert {c["term"] for c in module().collect(draft, "en")} == {"CPU", "GPT-4"}


@pytest.mark.parametrize("locale", ["th", "en"])
def test_fallback_includes_abbreviations_starting_with_numbers(locale):
    draft = script(card("เปิด 2FA แล้วดู 4K กับ 3D ในปี 2026", "เปิดทูเอฟเอแล้วดูโฟร์เคกับทรีดีในปีสองพันยี่สิบหก"))
    assert {c["term"] for c in module().collect(draft, locale)} == {"2FA", "4K", "3D"}


@pytest.mark.parametrize("locale", ["th", "en"])
def test_fallback_keeps_symbolic_names_distinct(locale):
    draft = script(card("ใช้ C++ กับ C# และ C++17", "ใช้ซีพลัสพลัสกับซีชาร์ปและซีพลัสพลัสสิบเจ็ด"))
    assert {c["term"] for c in module().collect(draft, locale)} == {"C++", "C#", "C++17"}


def test_high_risk_terms_appear_before_loanwords():
    draft = script(card("Docker Google CPU GPT-4", "ด็อกเกอร์กูเกิลซีพียูจีพีทีโฟร์", [
        check("Docker", "ด็อกเกอร์"), check("Google", "กูเกิล", "proper_name"),
        check("CPU", "ซีพียู", "acronym"), check("GPT-4", "จีพีทีโฟร์", "model_name"),
    ]))
    assert [c["term"] for c in module().collect(draft)] == ["CPU", "GPT-4", "Google", "Docker"]


def test_checklist_shows_cards_script_reading_and_override_notice():
    draft = script(card("CPU", "ซีพียู", [check("CPU", "ซีพียู", "acronym")]))
    text = module().format_checks(draft)
    assert "CPU → ซีพียู" in text and "card 1" in text
    assert "ยังไม่ได้ตรวจเสียงจริง" in text
    assert "/say" in text and "/redo" in text


def test_empty_checklist_does_not_claim_the_audio_passed():
    text = module().format_checks(script(card("ข้าวหุงสุก", "ข้าวหุงสุก")))
    assert "ไม่พบคำที่เข้าข่าย" in text and "ยังควรฟังคลิป" in text


def test_long_checklist_is_not_silently_truncated():
    draft = script(*(card(f"Model{i}", f"รุ่นที่{i}") for i in range(100)))
    text = module().format_checks(draft)
    assert len(text) > 4096 and "Model99" in text
