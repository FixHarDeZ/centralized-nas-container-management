import asyncio
import json
import os
import subprocess

os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

import pytest
from app import script, shop_studio, storyboard, studio

BRIEF = "หูฟังไร้สาย ราคา 299 บาท แบต 30 ชั่วโมง https://shp.ee/abc"
LOCK = "the same 25-year-old Thai woman with a long ponytail"
PITCH = {
    "title": "หูฟังแบตอึด", "caption": "แบตอยู่ทั้งวัน", "hashtags": ["#หูฟัง"],
    "beats": [
        {"badge": "แบต 30 ชม.", "lines": ["แบตอยู่ได้ 30 ชั่วโมงค่ะ"],
         "narration": "แบตอยู่ได้ 30 ชั่วโมงค่ะ", "spoken": "แบตอยู่ได้ 30 ชั่วโมงค่ะ", "photo": 2},
        {"badge": "299 บาท", "lines": ["ราคาแค่ 299 บาทค่ะ"],
         "narration": "ราคาแค่ 299 บาทค่ะ", "spoken": "ราคาแค่ 299 บาทค่ะ", "photo": 1},
    ],
    "end_badge": "กดตะกร้า", "end_narration": "กดตะกร้าได้เลยค่ะ", "end_spoken": "กดตะกร้าได้เลยค่ะ",
}


def test_every_beat_is_a_shot_and_the_closing_line_is_the_last():
    shots = shop_studio.shots(PITCH)
    assert [s["narration"] for s in shots] == [b["narration"] for b in PITCH["beats"]] + ["กดตะกร้าได้เลยค่ะ"]
    assert shots[-1]["lines"] == ["กดตะกร้าได้เลยค่ะ"] and shots[-1]["photo"] == 2
    assert shop_studio.script_for(PITCH)["cards"] == shots


@pytest.mark.parametrize("narration,spoken,needle", [
    ("ราคา 199 บาทค่ะ", "ราคา 199 บาทค่ะ", "ไม่มีใน Brief"),
    ("ราคา 299 บาทค่ะ", "ราคาสองร้อยเก้าสิบเก้าบาทค่ะ", "ตัวเลข"),
    ("ใช้ USB-C ค่ะ", "ใช้ USB ค่ะ", "ละติน"),
    ("ดีครับ", "ดีครับ", "ครับ"),
])
def test_a_shortened_line_keeps_the_shop_rules(narration, spoken, needle):
    problems = shop_studio.condense_check(BRIEF)(narration, spoken)
    assert any(needle in p for p in problems)


def test_a_clean_shortened_line_passes_and_rebuilds_its_subtitle():
    assert shop_studio.condense_check(BRIEF)("แบต 30 ชั่วโมงค่ะ", "แบต 30 ชั่วโมงค่ะ") == []
    card = dict(PITCH["beats"][0])
    shop_studio.apply_condensed(card, {"narration": "แบต 30 ชั่วโมงค่ะ", "spoken": "แบต 30 ชั่วโมงค่ะ"})
    assert card["lines"] == ["แบต 30 ชั่วโมงค่ะ"] and card["photo"] == 2


def test_condense_takes_the_shop_rules(monkeypatch):
    calls = []

    async def say(client, messages, temperature, budget):
        calls.append(messages)
        bad = len(calls) == 1
        text = "ราคา 199 บาทค่ะ" if bad else "ราคา 299 บาทค่ะ"
        return json.dumps({"cards": [{"card": 2, "narration": text, "spoken": text}]}, ensure_ascii=False)

    monkeypatch.setattr(script, "_say", say)
    monkeypatch.setattr(script, "_client", lambda: None)
    cards = shop_studio.shots(PITCH)
    out = asyncio.run(script.condense(cards, {1: 20}, "th", spoken_rule=shop_studio.SPOKEN_RULE,
                                      check=shop_studio.condense_check(BRIEF)))
    assert out[1]["narration"] == "ราคา 299 บาทค่ะ"
    assert "ตัวเลขคงเป็นตัวเลขอารบิก" in calls[0][0]["content"]
    assert "ไม่มีใน Brief" in calls[1][-1]["content"]


def board(n, product=True):
    return {"overview": {"title": "t", "title_en": "Earbuds That Last", "product_en": "wireless earbuds",
                         "mood_tone_progression": "m", "target_audience": "a",
                         "master_character": {"locked_prompt_tag": LOCK}},
            "scenes": [{"scene_number": i + 1, "camera": "c", "scene_description": "d",
                        "visual_details": "v", "scene_mood_note": "n", "sound_verbatim": "",
                        "on_screen_text": "",
                        "image_gen_prompt": f"{LOCK} holds {'@Product' if product else 'earbuds'} "
                                            "to camera, 9:16, no text, no watermark, no UI, no split-screen",
                        "motion": "Static camera"} for i in range(n)]}


def test_a_scene_that_forgot_the_product_gets_it_and_a_missing_title_is_filled(monkeypatch):
    calls = []

    async def say(client, messages, temperature, budget):
        calls.append(messages)
        data = board(3, product=False)
        del data["overview"]["title"]
        return json.dumps(data)

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    data = asyncio.run(shop_studio.plan(shop_studio.script_for(PITCH), {"text": BRIEF}, storyboard.AUTO))
    assert len(calls) == 1 and data["overview"]["title"] == PITCH["title"]
    prompt = data["scenes"][0]["image_gen_prompt"]
    assert "holds earbuds to camera, 9:16, holding @Product clearly in view, no text" in prompt


def test_plan_puts_the_product_in_every_scene_and_says_the_spoken_line(monkeypatch):
    calls = []

    async def say(client, messages, temperature, budget):
        calls.append(messages)
        return json.dumps(board(3))

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    script_ = shop_studio.script_for(PITCH)
    data = asyncio.run(shop_studio.plan(script_, {"text": BRIEF}, storyboard.AUTO))
    assert len(calls) == 1
    assert [s["sound_verbatim"] for s in data["scenes"]] == [c["spoken"] for c in script_["cards"]]
    assert [s["photo"] for s in data["scenes"]] == [2, 1, 2]
    brief = calls[0][1]["content"]
    assert shop_studio.WOMAN in brief and "299" in brief
    assert "@Product" in calls[0][0]["content"]
    md = storyboard.studio_markdown(data, "@Lead", {"language": "Thai"}, shop_studio.product_name(data))
    assert "Products:\n@Product is wireless earbuds, exactly as in the attached product photos" in md
    assert "Scene 1:\n@Lead holds @Product to camera." in md
    assert 'Dialogue: "แบตอยู่ได้ 30 ชั่วโมงค่ะ"' in md


def test_a_thai_or_missing_product_name_falls_back():
    data = board(1)
    data["overview"]["product_en"] = "หูฟัง"
    assert shop_studio.product_name(data) == "the product"


def test_shop_ids_are_clip_ids_and_ref_names_are_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert studio.root("p261020150000").name == "p261020150000"
    assert studio.ref_path("p261020150000", "photo2.jpg").name == "photo2.jpg"
    for bad in ("../x.jpg", "photo2.jpg/..", "a.png", "photo10.jpg"):
        with pytest.raises(ValueError):
            studio.ref_path("p261020150000", bad)
    photo = tmp_path / "p01.png"
    photo.write_bytes(b"png")
    assert shop_studio.copy_refs("p261020150000", [str(photo), str(tmp_path / "gone.jpg")]) == ["photo1.png"]


def test_build_renders_each_shot_with_its_own_voice(tmp_path, monkeypatch):
    """Real ffmpeg, Pillow and the shop layout: footage + voice per shot → one clip."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(shop_studio.render, "pick_music", lambda: None)
    clip_id = "p261020150000"
    script_ = shop_studio.script_for(PITCH)
    for i, length in enumerate((3, 3, 2)):
        video = studio.segment_path(clip_id, i)
        video.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={length}",
                        "-c:v", "libx264", "-preset", "ultrafast", str(video)], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={length - 1}",
                        "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-filter_complex",
                        "[1:a]atrim=0:1[s];[0:a][s]concat=n=2:v=0:a=1", "-ac", "1", "-ar", "24000",
                        str(studio.voice_path(clip_id, i))], check=True, capture_output=True)
    clip, details = shop_studio.build(script_, clip_id, tmp_path / "work")
    assert clip.is_file() and details["mode"] == "studio" and len(details["shots"]) == 3
    # Each shot runs as long as its voice with the tail silence trimmed (~0.3s kept).
    assert all(s["seconds"] < length for s, length in zip(details["shots"], (3, 3, 2)))
    assert 4.0 < details["seconds"] < 7.0


def test_a_line_that_runs_to_the_end_of_its_shot_still_renders(tmp_path, monkeypatch):
    """No tail silence to trim, footage no longer than the voice: the footage wins."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(shop_studio.render, "pick_music", lambda: None)
    clip_id = "p261020150001"
    one = {**PITCH, "beats": PITCH["beats"][:1]}
    for i in range(2):
        video = studio.segment_path(clip_id, i)
        video.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=24:duration=2",
                        "-c:v", "libx264", "-preset", "ultrafast", str(video)], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2.2",
                        "-ac", "1", "-ar", "24000", str(studio.voice_path(clip_id, i))],
                       check=True, capture_output=True)
    clip, details = shop_studio.build(shop_studio.script_for(one), clip_id, tmp_path / "work")
    assert clip.is_file() and all(s["seconds"] <= 2.0 for s in details["shots"])


def test_a_lower_case_product_tag_is_fixed_not_refused(monkeypatch):
    async def say(client, messages, temperature, budget):
        data = board(3)
        for scene in data["scenes"]:
            scene["image_gen_prompt"] = scene["image_gen_prompt"].replace("@Product", "@product")
        return json.dumps(data)

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    data = asyncio.run(shop_studio.plan(shop_studio.script_for(PITCH), {"text": BRIEF}, storyboard.AUTO))
    assert all("@Product" in s["image_gen_prompt"] for s in data["scenes"])
