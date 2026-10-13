"""Product Clips (docs/adr/0015): the Pitch rules, the Brief's state, routing.

Run inside the image like the rest of the suite; the one render test needs
Raqm, the Thai font and ffmpeg.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import shutil

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "42")
os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

from app import backfill, main, shop
from app import state as st

BRIEF = """หูฟังไร้สาย รุ่น X2 ราคา ฿1,299 จากปกติ 1,990 บาท
แบตอยู่ได้ 30 ชั่วโมง กันน้ำ IPX4 ชาร์จ USB-C
https://s.shopee.co.th/AbCdEf"""


def a_beat(narration="หูฟังไร้สายตัวนี้ แบตอยู่ได้ 30 ชั่วโมง", photo=1) -> dict:
    half = len(narration) // 2
    return {"badge": "แบตอึด", "lines": [narration[:half], narration[half:]],
            "narration": narration, "spoken": narration, "photo": photo}


def a_pitch(**changes) -> dict:
    pitch = {
        "title": "หูฟังไร้สาย แบตอึดทั้งวัน",
        "beats": [a_beat(), a_beat("กันน้ำ ใส่วิ่งได้สบาย", 2), a_beat("ชาร์จผ่าน USB-C", 1)],
        "price": "1,299", "old_price": "1990",
        "end_badge": "ของมันต้องมี",
        "end_narration": "กดลิงก์ในคอมเมนต์ได้เลยค่ะ",
        "end_spoken": "กดลิงก์ในคอมเมนต์ได้เลยค่ะ",
        "caption": "หูฟังที่ใช้ได้ทั้งวัน",
        "hashtags": ["#หูฟังไร้สาย", "#shopee"],
    }
    pitch["beats"][2]["spoken"] = "ชาร์จผ่านยูเอสบีซี"
    pitch.update(changes)
    return pitch


async def _nothing(*args, **kwargs):
    return {"message_id": 7}


# --- the Pitch ----------------------------------------------------------------

def test_a_good_pitch_passes_and_prices_are_normalised():
    pitch = shop.validate(a_pitch(), BRIEF, photos=2)
    assert pitch["price"] == "1299" and pitch["old_price"] == "1990"


@pytest.mark.parametrize("mutate,why", [
    (lambda p: p["beats"][0].update(narration="แบตอยู่ได้ 40 ชั่วโมง", spoken="แบตอยู่ได้ 40 ชั่วโมง",
                                     lines=["แบตอยู่ได้ 40 ชั่วโมง"]), "invented number"),
    (lambda p: p["beats"][0].update(narration="รีวิว 5 ดาว", spoken="รีวิว 5 ดาว",
                                     lines=["รีวิว 5 ดาว"]), "a single digit is a claim here"),
    (lambda p: p["beats"][0].update(badge="ลด 35%"), "percent written by the model"),
    (lambda p: p["beats"][0].update(lines=["บรรทัดที่ไม่ตรงกับเสียงพูด"]), "subtitle is not the narration"),
    (lambda p: p["beats"][0].update(narration="ก" * 60, spoken="ก" * 60, lines=["ก" * 60]), "line too wide"),
    (lambda p: p.update(end_narration="กดลิงก์เลยครับ", end_spoken="กดลิงก์เลยครับ"), "male particle"),
    (lambda p: p["beats"][2].update(spoken="ชาร์จผ่าน USB-C"), "latin in spoken"),
    (lambda p: p["beats"][0].update(spoken="หูฟังไร้สายตัวนี้ แบตอยู่ได้ สามสิบ ชั่วโมง"), "number spelled out in spoken"),
    (lambda p: p["beats"][0].update(photo=3), "photo out of range"),
    (lambda p: p.update(price="999"), "price not in the brief"),
    (lambda p: p.update(caption="ดูที่ https://example.com"), "link in the text"),
    (lambda p: p.update(beats=p["beats"][:2]), "too few beats"),
])
def test_a_bad_pitch_is_sent_back(mutate, why):
    pitch = a_pitch()
    mutate(pitch)
    with pytest.raises(shop.PitchError):
        shop.validate(pitch, BRIEF, photos=2)


def test_prices_as_shopee_writes_them_are_found_in_the_brief():
    assert shop.unsourced("ราคา 1,299 บาท", "ราคา ฿1,299.-") == []
    assert shop.unsourced("ราคา 1299", "ราคา 1,299 บาท") == []


def test_numbers_inside_the_link_do_not_count_as_sources():
    assert shop.unsourced("รุ่น 12345", "https://s.shopee.co.th/12345") == ["12345"]


def test_the_discount_is_computed_not_written():
    assert shop.discount("1299", "1990") == 35
    assert shop.discount("299", "") is None
    assert shop.discount("500", "400") is None


def test_the_link_prefers_shopee():
    text = "ดูรีวิว https://youtu.be/x แล้วซื้อ https://s.shopee.co.th/AbCdEf"
    assert shop.link_in(text) == "https://s.shopee.co.th/AbCdEf"


def test_the_caption_always_discloses():
    caption = shop.caption_text(a_pitch(), "https://s.shopee.co.th/AbCdEf")
    assert "#ad" in caption and "affiliate" in caption
    assert "https://s.shopee.co.th/AbCdEf" in caption
    assert "#ad" in shop.caption_text(a_pitch(), None)


def test_a_rejected_pitch_goes_back_to_the_model_with_the_reason(monkeypatch):
    bad = a_pitch(price="999")
    replies = [json.dumps(bad, ensure_ascii=False), json.dumps(a_pitch(), ensure_ascii=False)]
    asked = []

    async def fake_say(client, messages, temperature, budget, model=None):
        asked.append(list(messages))
        return replies.pop(0)

    monkeypatch.setattr(shop.script_gen, "_say", fake_say)
    monkeypatch.setattr(shop.script_gen, "_client", lambda: None)
    pitch = asyncio.run(shop.generate(BRIEF, 2))
    assert pitch["price"] == "1299"
    assert "price" in asked[1][-1]["content"]


# --- the Brief's state --------------------------------------------------------

def test_a_brief_holds_the_bot_and_idle_clears_it():
    state = {"mode": "idle"}
    st.open_shop(state, "p1")
    assert state["mode"] in st.HOLDING_MODES
    st.to_idle(state)
    assert state["mode"] == "idle" and "shop" not in state


def test_opening_a_brief_drops_a_pending_auto_pick():
    state = {"mode": "idle", "auto_pick": {"deadline": "2000-01-01T00:00:00"}}
    st.open_shop(state, "p1")
    assert "auto_pick" not in state
    assert st.claim_auto_pick({"mode": st.SHOP_MODE, "auto_pick": {"deadline": "2000-01-01T00:00:00"}}) is False


def test_a_brief_waiting_on_the_human_expires_and_a_working_one_does_not():
    old = (datetime.datetime.now() - st.SHOP_LIFETIME - datetime.timedelta(minutes=1)).isoformat()
    for phase, expires in (("collect", True), ("review", True), ("writing", False), ("rendering", False)):
        state = {"mode": st.SHOP_MODE, "shop": {"phase": phase, "touched_at": old}}
        assert st.shop_expired(state) is expires, phase
    assert not st.review_expired({"mode": st.SHOP_MODE, "review_at": old})


def test_a_restart_mid_job_puts_the_brief_back_in_front_of_the_human():
    state = {"mode": st.SHOP_MODE, "shop": {"phase": "rendering", "pitch": a_pitch()}}
    assert st.recover_shop(state)
    assert state["shop"]["phase"] == "review"
    state = {"mode": st.SHOP_MODE, "shop": {"phase": "writing", "pitch": None}}
    st.recover_shop(state)
    assert state["shop"]["phase"] == "collect"
    state = {"mode": st.SHOP_MODE}
    st.recover_shop(state)
    assert state["mode"] == "idle"


# --- routing -----------------------------------------------------------------

@pytest.fixture
def bot(monkeypatch, tmp_path):
    said = []

    async def fake_say(client, text, **extra):
        said.append(text)
        return {"message_id": len(said)}

    spawned = []
    monkeypatch.setattr(main, "say", fake_say)
    monkeypatch.setattr(main, "api", _nothing)
    monkeypatch.setattr(main, "save_state", lambda state: None)
    monkeypatch.setattr(main, "spawn", lambda coro, label: (spawned.append(label), coro.close()))
    monkeypatch.setattr(main, "SHOP_DIR", tmp_path / "shop")
    return said, spawned


def _photo_update(file_id, caption=None):
    message = {"chat": {"id": 42}, "photo": [{"file_id": "small"}, {"file_id": file_id, "file_size": 10}]}
    if caption:
        message["caption"] = caption
    return {"message": message}


def test_a_topic_while_a_brief_is_open_is_text_for_the_brief(bot):
    _said, spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    asyncio.run(main.on_text(None, state, "ราคา 299 บาท"))
    assert "ราคา 299" in state["shop"]["text"]
    assert "make_script" not in spawned


def test_photos_are_numbered_in_arrival_order_and_captions_kept(bot):
    _said, spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    asyncio.run(main.handle(None, state, _photo_update("a", caption=BRIEF)))
    asyncio.run(main.handle(None, state, _photo_update("b")))
    photos = state["shop"]["photos"]
    assert [pathlib.Path(p).stem for p in photos] == ["p01", "p02"]
    assert spawned.count("shop_photo") == 2
    assert "s.shopee.co.th" in state["shop"]["text"]


def test_an_image_sent_as_a_file_is_a_product_photo_not_footage(bot):
    _said, spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    update = {"message": {"chat": {"id": 42}, "document": {
        "file_id": "f", "mime_type": "image/png", "file_name": "x.png", "file_size": 10}}}
    asyncio.run(main.handle(None, state, update))
    assert state["shop"]["photos"][0].endswith("p01.png")
    assert "on_footage" not in spawned


def test_a_photo_without_a_brief_says_how_to_start(bot):
    said, _ = bot
    asyncio.run(main.handle(None, {"mode": "idle"}, _photo_update("a")))
    assert "/shop" in said[-1]


def test_shop_is_refused_while_a_script_is_in_review(bot):
    _said, _ = bot
    state = {"mode": "review", "script": {}}
    asyncio.run(main.on_text(None, state, "/shop"))
    assert "shop" not in state


def test_a_button_from_an_older_brief_does_nothing(bot):
    _said, _spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": "shop:drop:p0"}))
    assert state["mode"] == st.SHOP_MODE
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": f"shop:drop:{state['shop']['id']}"}))
    assert state["mode"] == "idle"


def test_go_waits_for_every_photo_to_land(bot, tmp_path):
    _said, spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop " + BRIEF))
    state["shop"]["photos"] = [str(tmp_path / "missing.jpg")]
    data = f"shop:go:{state['shop']['id']}"
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": data}))
    assert "shop_write" not in spawned
    (tmp_path / "missing.jpg").write_bytes(b"x")
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": data}))
    assert "shop_write" in spawned


# --- kept out of the Shorts record -------------------------------------------

def test_backfill_never_reads_a_product_caption(monkeypatch, tmp_path):
    """backfill files a caption by its first line; a Product Clip's caption
    whose title matched a published Short would come back as that Short."""
    out = tmp_path / "output"
    (out / "shop" / "p1").mkdir(parents=True)
    (out / "shop" / "p1" / "caption.txt").write_text("หูฟังไร้สาย\n\nlink", encoding="utf-8")
    (out / "en").mkdir()
    (out / "en" / "a.txt").write_text("English title\n", encoding="utf-8")
    monkeypatch.setattr(backfill, "OUTPUT_DIR", out)
    assert list(backfill._files_by_title()) == ["English title"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs the image")
def test_a_pitch_renders_to_a_vertical_clip(monkeypatch, tmp_path):
    from PIL import Image, features
    if not features.check("raqm"):
        pytest.skip("needs Raqm")
    from app import render, shop_render

    async def fake_track(cards, workdir, locale="th", voice=None):
        audio = workdir / "a.wav"
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                     "-t", str(len(cards)), str(audio)])
        return audio, [float(i) for i in range(len(cards))]

    monkeypatch.setattr(render, "_narration_track", fake_track)
    monkeypatch.setattr(render, "pick_music", lambda: None)
    photos = []
    for i, size in enumerate([(800, 1200), (1600, 900)]):
        path = tmp_path / f"p{i}.jpg"
        Image.new("RGB", size, (200, 100, 50)).save(path)
        photos.append(path)
    pitch = shop.validate(a_pitch(), BRIEF, photos=2)
    clip, details = asyncio.run(shop_render.build(pitch, photos, tmp_path / "work"))
    assert clip.is_file() and details["frame"] == [1080, 1920]
    assert len(details["beats"]) == 4


def test_a_double_tap_writes_one_pitch(bot, tmp_path):
    _, spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop " + BRIEF))
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    state["shop"]["photos"] = [str(photo)]
    data = f"shop:go:{state['shop']['id']}"
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": data}))
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": data}))
    assert spawned.count("shop_write") == 1


def test_a_double_tap_renders_once(bot):
    _, spawned = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    st.shop_phase(state, "review", pitch=a_pitch())
    data = f"shop:render:{state['shop']['id']}"
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": data}))
    asyncio.run(main.on_callback(None, state, {"id": "q", "data": data}))
    assert spawned.count("shop_render") == 1


def test_a_failed_download_never_lets_two_photos_share_a_name(bot, monkeypatch):
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    asyncio.run(main.handle(None, state, _photo_update("a")))
    asyncio.run(main.handle(None, state, _photo_update("b")))

    async def failed(client, file_id, dest):
        return False

    monkeypatch.setattr(main, "download_footage", failed)
    asyncio.run(main._fetch_shop_photo(None, state, state["shop"]["id"], "b",
                                       pathlib.Path(state["shop"]["photos"][1])))
    asyncio.run(main.handle(None, state, _photo_update("c")))
    photos = state["shop"]["photos"]
    assert len(photos) == 2 and len(set(photos)) == 2


def test_a_heic_file_is_refused_on_arrival(bot):
    said, _ = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    update = {"message": {"chat": {"id": 42}, "document": {
        "file_id": "f", "mime_type": "image/heic", "file_name": "IMG_1.HEIC", "file_size": 10}}}
    asyncio.run(main.handle(None, state, update))
    assert state["shop"]["photos"] == []
    assert "JPG" in said[-1]


def test_shop_while_a_brief_is_open_puts_its_buttons_back(bot):
    said, _ = bot
    state = {"mode": "idle"}
    asyncio.run(main.on_text(None, state, "/shop"))
    st.shop_phase(state, "review", pitch=a_pitch())
    asyncio.run(main.on_text(None, state, "/shop"))
    assert said[-1].startswith("🛍 " + a_pitch()["title"])


def test_after_a_restart_the_brief_comes_back_with_buttons(bot):
    state = {"mode": st.SHOP_MODE, "shop": {"id": "p1", "phase": "rendering", "pitch": a_pitch(),
                                            "photos": [], "text": BRIEF}}
    assert st.recover_shop(state)
    asyncio.run(main.shop_resume(None, state))
    assert state["shop"]["message_id"] is not None
