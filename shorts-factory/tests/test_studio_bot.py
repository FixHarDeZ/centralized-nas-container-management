import asyncio
import json
import os
import pathlib

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "42")
os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

import pytest  # noqa: E402

from app import characters, main, storyboard, studio  # noqa: E402

CLIP = "20261015-170226-065"
LOCK = "the same 28-year-old Thai woman with a short black bob"
SPAWNED = []


def run(coro):
    """Run a handler, then everything it spawned, in order (spawn is patched)."""
    async def go():
        await coro
        while SPAWNED:
            await SPAWNED.pop(0)
    asyncio.run(go())


def a_script(n=3):
    return {"title": "หัวข้อ", "description": "", "hashtags": [], "cards": [
        {"lines": [f"การ์ด {i}"], "narration": f"พูด {i}", "spoken": f"พูด {i}", "query": "q"}
        for i in range(n)]}


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("SHOP_PUBLIC_URL", "https://nas.example")
    (tmp_path / "config").mkdir()
    sent = []

    async def say(client, text, **extra):
        sent.append(("say", text, extra))
        return {"message_id": 100 + len(sent)}

    async def send_document(client, path, caption="", **extra):
        sent.append(("doc", pathlib.Path(path).read_text(encoding="utf-8"), extra))
        return {"message_id": 100 + len(sent)}

    async def close(*args, **kwargs):
        return None

    async def narration(script, locale, clip_id):
        return {"audio": "x", "starts": [0.0, 7.0, 16.0], "total": 24.0,
                "spans": [7.0, 9.0, 8.2], "say": ""}

    async def board(script, pending, shots, **kwargs):
        sent.append(("board", kwargs, pending))
        scenes = [{"card": c, "image_gen_prompt": f"{LOCK} at a desk, 9:16, no text",
                   "motion": "slow push in", "sound_verbatim": script["cards"][c]["narration"]}
                  for c in pending for _ in range(shots[c])]
        return {"overview": {"title": "t", "master_character": {"locked_prompt_tag": LOCK}},
                "scenes": scenes, "ratio": "9:16"}

    monkeypatch.setattr(main, "say", say)
    monkeypatch.setattr(main, "send_document", send_document)
    monkeypatch.setattr(main, "close_prompt", close)
    monkeypatch.setattr(main, "save_state", lambda state: None)
    SPAWNED.clear()
    monkeypatch.setattr(main, "spawn", lambda coro, label: SPAWNED.append(coro))
    monkeypatch.setattr(studio, "prepare_narration", narration)
    monkeypatch.setattr(storyboard, "for_studio", board)
    return sent


def review_state():
    return {"mode": "review", "script": a_script(), "clip_id": CLIP, "topic": "หัวข้อ",
            "locale": "th", "message_id": 9}


def test_studio_button_builds_a_hook_pack_and_frees_the_bot(bot):
    state = review_state()
    run(main.on_studio(None, state))
    wait = state["clip_wait"]
    assert state["mode"] == "idle" and wait["kind"] == "studio"
    assert wait["sources"] == ["flow", "pexels", "pexels"]
    (token, version), = wait["versions"].items()
    assert version["pending"] == [0] and version["shots"] == {"0": 1}
    pack = studio.read_pack(CLIP)
    assert pack["token"] == token and pack["total_shots"] == 1 and pack["credits"] == 12
    doc = next(item for item in bot if item[0] == "doc")
    assert "[SCENE 1]" in doc[1] and "@Lead" in doc[1]
    message = next(item for item in bot if item[0] == "say" and "Studio pack" in item[1])
    assert "https://nas.example/storyboard/" + CLIP in message[1]


def test_toggling_a_card_makes_a_new_version(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stt:{CLIP}:1"))
    wait = state["clip_wait"]
    assert wait["sources"] == ["flow", "flow", "pexels"]
    newest = studio.read_pack(CLIP)
    assert newest["pending"] == [0, 1] and newest["shots"] == {"0": 1, "1": 2}
    assert len(wait["versions"]) == 2


def test_all_pexels_renders_without_a_pack(bot, monkeypatch):
    rendered = []

    async def fake_render(client, state, clip_id):
        rendered.append(clip_id)

    monkeypatch.setattr(main, "render_studio", fake_render)
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stp:{CLIP}"))
    assert rendered == [CLIP] and state["clip_wait"]["sources"] == ["pexels"] * 3


def test_library_default_character_is_used_and_translated_once(bot, monkeypatch, tmp_path):
    characters.save({"characters": [{"id": "nong", "tag": "@Nong", "thai": "ผู้หญิงไทย",
                                      "english": "", "flow_ready": True}],
                     "defaults": {"th": "nong"}, "footage": "hook"})
    calls = []

    async def english(thai):
        calls.append(thai)
        return LOCK

    monkeypatch.setattr(storyboard, "english_character", english)
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stt:{CLIP}:2"))
    assert calls == ["ผู้หญิงไทย"]
    boards = [item for item in bot if item[0] == "board"]
    assert boards[0][1]["fixed_tag"] == LOCK and boards[0][1]["choice"] == storyboard.OWN
    pack = studio.read_pack(CLIP)
    assert pack["character"]["tag"] == "@Nong" and pack["character"]["flow_ready"] is True


def test_switching_character_to_none(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stc:{CLIP}:none"))
    assert state["clip_wait"]["choice"] == "none"
    assert [item for item in bot if item[0] == "board"][-1][1]["choice"] == storyboard.NONE


def test_stale_callback_is_refused(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, "stt:20200101-000000-000:0"))
    assert any("เก่าแล้ว" in item[1] for item in bot if item[0] == "say")


def test_shorten_returns_the_script_to_review(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stx:{CLIP}"))
    assert state["mode"] == "review" and "clip_wait" not in state
    assert any("การ์ด 2" in item[1] for item in bot if item[0] == "say")


def test_review_keyboard_offers_studio():
    flat = [b["callback_data"] for row in main.REVIEW_KEYBOARD["inline_keyboard"] for b in row]
    assert main.STUDIO_CB in flat


def test_shorten_gives_a_queued_pair_back(bot):
    state = review_state()
    state["pair"] = {"pair_id": CLIP, "topic": "หัวข้อ"}
    run(main.on_studio(None, state))
    assert "pair" not in state
    run(main.on_studio_callback(None, state, f"stx:{CLIP}"))
    assert state["mode"] == "review" and state["pair"]["pair_id"] == CLIP


def test_a_failed_plan_leaves_the_pack_usable(bot, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("mimo stalled")

    monkeypatch.setattr(storyboard, "for_studio", broken)
    state = review_state()
    run(main.on_studio(None, state))
    wait = state["clip_wait"]
    assert wait["busy"] is False and wait["versions"] == {}
    failed = [item for item in bot if item[0] == "say" and "ไม่สำเร็จ" in item[1]][-1]
    assert f"stt:{CLIP}:0" in json.dumps(failed[2])


def test_shorten_keeps_the_fact_sheet_and_variant(bot):
    state = review_state()
    facts = {"query": "หัวข้อ", "results": [{"title": "แหล่ง", "url": "https://example.invalid/a",
                                           "content": "ตัวเลข 42"}]}
    state.update(research=facts, style="hook-b")
    run(main.on_studio(None, state))
    assert state["research"] is None and state["clip_wait"]["research"] == facts
    run(main.on_studio_callback(None, state, f"stx:{CLIP}"))
    assert state["research"] == facts and state["style"] == "hook-b"
    assert any("📎 https://example.invalid/a" in item[1] for item in bot if item[0] == "say")


import subprocess  # noqa: E402


def testsrc(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-f", "mp4", str(path)], check=True, capture_output=True)
    return path


testsrc.__test__ = False  # a helper, not a test: pytest collects any `test*` name


def capture_render(monkeypatch):
    calls = []

    async def fake(client, state, supplied=None, narration=None, hold=frozenset()):
        calls.append({"supplied": supplied, "narration": narration, "hold": set(hold),
                      "clip_id": state.get("clip_id")})

    monkeypatch.setattr(main, "do_render", fake)
    return calls


def studio_ready(bot):
    state = review_state()
    run(main.on_studio(None, state))
    token, = state["clip_wait"]["versions"]
    return state, token


def test_inbox_export_is_cut_and_rendered_with_the_saved_take(bot, monkeypatch, tmp_path):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: (pathlib.Path("take.wav"), [0.0, 7.0, 16.0]))
    state, token = studio_ready(bot)
    inbox = studio.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    testsrc(inbox / f"{token}.mp4", 8)
    (claimed_token, path), = studio.claim_inbox({token})
    asyncio.run(main.process_export(None, state, claimed_token, path))
    assert calls and calls[0]["hold"] == {0}
    assert calls[0]["supplied"] == {0: studio.segment_path(CLIP, 0)}
    assert calls[0]["narration"][1] == [0.0, 7.0, 16.0]
    assert not path.exists()


def test_wrong_length_waits_for_cut_evenly(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: None)
    state, token = studio_ready(bot)
    inbox = studio.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    path = testsrc(inbox / f"{token}.mp4.taken", 5)
    asyncio.run(main.process_export(None, state, token, path))
    assert not calls and token in state["clip_wait"]["uneven"]
    assert any("cut evenly" in str(item[2]) or "หั่นเท่า" in str(item[2]) for item in bot if item[0] == "say")
    run(main.on_studio_callback(None, state, f"ste:{CLIP}:{token}"))
    assert calls and calls[0]["narration"] is None
    assert any("/say" in item[1] for item in bot if item[0] == "say")


def test_busy_bot_keeps_a_render_button(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state, token = studio_ready(bot)
    state["mode"] = "rendering"
    asyncio.run(main.render_studio(None, state, CLIP))
    assert not calls
    last = [item for item in bot if item[0] == "say"][-1]
    assert f"str:{CLIP}" in json.dumps(last[2])


def test_reply_routes_to_the_version_it_answered(bot, monkeypatch):
    state, token = studio_ready(bot)
    monkeypatch.setattr(main, "is_ours", lambda update: True)
    labels = []
    monkeypatch.setattr(main, "spawn", lambda coro, label: labels.append(label) or coro.close())
    message_id = state["clip_wait"]["versions"][token]["message_id"]
    for replied, expected in ((message_id, "on_studio_reply"), (1, "on_footage")):
        message = {"video": {"file_id": "f", "file_size": 10}, "reply_to_message": {"message_id": replied}}
        asyncio.run(main.handle(None, state, {"message": message}))
    assert labels == ["on_studio_reply", "on_footage"]


def test_oversize_reply_points_to_the_web_page(bot):
    state, token = studio_ready(bot)
    message = {"video": {"file_id": "f", "file_size": main.TELEGRAM_FILE_LIMIT + 1}}
    asyncio.run(main.on_studio_reply(None, state, message, token))
    assert any("/storyboard/" in item[1] for item in bot if item[0] == "say")


def test_flow_to_pexels_after_render_keeps_other_footage(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: None)
    state, token = studio_ready(bot)
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    state["clip_wait"]["sources"] = ["flow", "flow", "pexels"]
    state["clip_wait"]["versions"].clear()
    run(main.on_studio_callback(None, state, f"stt:{CLIP}:1"))
    assert calls and calls[-1]["hold"] == {0}


def test_a_flow_card_without_footage_is_never_rendered_on_pexels(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state, token = studio_ready(bot)
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    state["clip_wait"]["sources"] = ["flow", "flow", "pexels"]
    run(main.render_studio(None, state, CLIP))
    assert not calls
    assert any("การ์ด 2" in item[1] for item in bot if item[0] == "say")


def test_a_queued_pair_waits_inside_the_studio_pack(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state = review_state()
    state["pair"] = {"pair_id": CLIP, "topic": "หัวข้อ"}
    run(main.on_studio(None, state))
    assert "pair" not in state and state["clip_wait"]["pair"]["pair_id"] == CLIP
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    run(main.render_studio(None, state, CLIP))
    assert calls and state["pair"]["pair_id"] == CLIP


def test_a_second_studio_pack_is_refused_while_one_is_live(bot):
    state = review_state()
    run(main.on_studio(None, state))
    other = {**review_state(), "clip_id": "20261016-090000-000",
             "clip_wait": state["clip_wait"]}
    run(main.on_studio(None, other))
    assert other["mode"] == "review" and other["clip_wait"]["clip_id"] == CLIP
    assert any("ค้างอยู่" in item[1] for item in bot if item[0] == "say")


def test_redo_keeps_the_flow_footage(bot, monkeypatch):
    rendered = []

    async def fake(client, state, clip_id):
        rendered.append(clip_id)

    monkeypatch.setattr(main, "render_studio", fake)
    state, token = studio_ready(bot)
    state.update(last_script=state["clip_wait"]["script"], last_clip_id=CLIP, mode="idle")
    run(main.on_redo(None, state))
    assert rendered == [CLIP]


def test_upload_success_cleans_the_studio_files(bot, monkeypatch, tmp_path):
    state, token = studio_ready(bot)
    assert studio.read_pack(CLIP)
    main.finish_studio_after_upload(state, CLIP)
    assert "clip_wait" not in state and studio.read_pack(CLIP) is None


def test_render_studio_restores_the_fact_sheet_and_variant(bot, monkeypatch):
    seen = []

    async def fake(client, state, supplied=None, narration=None, hold=frozenset()):
        seen.append((state.get("style"), state.get("research")))

    monkeypatch.setattr(main, "do_render", fake)
    facts = {"query": "หัวข้อ", "results": []}
    state = review_state()
    state.update(research=facts, style="hook-b")
    run(main.on_studio(None, state))
    assert state.get("research") is None
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    run(main.render_studio(None, state, CLIP))
    assert seen == [("hook-b", facts)]


def test_a_reply_to_script_md_routes_too(bot, monkeypatch):
    state, token = studio_ready(bot)
    doc_id = next(100 + i + 1 for i, item in enumerate(bot) if item[0] == "doc")
    assert doc_id != state["clip_wait"]["versions"][token]["message_id"]
    monkeypatch.setattr(main, "is_ours", lambda update: True)
    labels = []
    monkeypatch.setattr(main, "spawn", lambda coro, label: labels.append(label) or coro.close())
    message = {"video": {"file_id": "f", "file_size": 10}, "reply_to_message": {"message_id": doc_id}}
    asyncio.run(main.handle(None, state, {"message": message}))
    assert labels == ["on_studio_reply"]


def test_a_storyboard_over_a_live_pack_drops_it_out_loud(bot, monkeypatch):
    state, token = studio_ready(bot)
    state["clip_wait"]["pair"] = {"pair_id": CLIP, "topic": "หัวข้อ"}
    held = studio.inbox_dir() / f"{token}.mp4.taken"
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_bytes(b"x")

    async def board(*args, **kwargs):
        return {"overview": {"title": "t"}, "scenes": []}

    async def send(client, board):
        return 555

    monkeypatch.setattr(storyboard, "for_script", board)
    monkeypatch.setattr(main, "send_storyboard", send)
    run(main.on_storyboard(None, state, script=a_script(), clip_id=CLIP))
    assert state["clip_wait"]["message_id"] == 555 and "kind" not in state["clip_wait"]
    assert studio.read_pack(CLIP) is None and not held.exists()
    note = [item[1] for item in bot if item[0] == "say"][-1]
    assert "Studio pack" in note and "อังกฤษ" in note


def test_a_studio_pack_over_a_storyboard_wait_says_so(bot):
    state = review_state()
    state["clip_wait"] = {"message_id": 7, "script": {"title": "บอร์ดเก่า"}, "topic": "x",
                          "locale": "th", "created_at": "2026-10-16T08:00:00"}
    run(main.on_studio(None, state))
    assert state["clip_wait"]["kind"] == "studio"
    assert any("บอร์ดเก่า" in item[1] for item in bot if item[0] == "say")


def test_a_failed_cut_leaves_no_inbox_file(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state, token = studio_ready(bot)
    inbox = studio.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    path = testsrc(inbox / f"{token}.mp4.taken", 8)

    def broken(*args, **kwargs):
        raise RuntimeError("ffmpeg died")

    monkeypatch.setattr(studio, "cut", broken)
    asyncio.run(main.process_export(None, state, token, path))
    assert not calls and not path.exists()
    assert any("ffmpeg died" in item[1] for item in bot if item[0] == "say")


def test_expiry_cleans_a_held_export(bot):
    state, token = studio_ready(bot)
    held = studio.inbox_dir() / f"{token}.mp4.taken"
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_bytes(b"x")
    main.drop_studio_files(state.pop("clip_wait"))
    assert not held.exists() and studio.read_pack(CLIP) is None


def capture_api(monkeypatch):
    calls = []

    async def api(client, method, **payload):
        calls.append((method, payload))
        return {}

    monkeypatch.setattr(main, "api", api)
    return calls


def a_tap(data, text="🎞 Studio pack v1 — หัวข้อ"):
    return {"id": "q1", "data": data, "message": {"message_id": 77, "text": text}}


def test_a_toggle_tap_says_so_at_once_and_ticks_the_tapped_message(bot, monkeypatch):
    state = review_state()
    run(main.on_studio(None, state))
    calls = capture_api(monkeypatch)
    asyncio.run(main.on_callback(None, state, a_tap(f"stt:{CLIP}:2")))
    answers = [p for m, p in calls if m == "answerCallbackQuery"]
    assert len(answers) == 1 and "การ์ด 3 → 🎬 Flow" in answers[0]["text"]
    assert "pack v2" in answers[0]["text"]
    (edit,) = [p for m, p in calls if m == "editMessageText"]
    assert edit["message_id"] == 77 and "⏳" in edit["text"]
    assert "3 🎬" in json.dumps(edit["reply_markup"], ensure_ascii=False)
    for coro in SPAWNED:
        coro.close()
    SPAWNED.clear()


def test_a_second_tap_while_busy_is_a_toast_not_a_chat_line(bot, monkeypatch):
    state = review_state()
    run(main.on_studio(None, state))
    state["clip_wait"]["busy"] = True
    calls = capture_api(monkeypatch)
    before = len(bot)
    asyncio.run(main.on_callback(None, state, a_tap(f"stt:{CLIP}:1")))
    (answer,) = [p for m, p in calls if m == "answerCallbackQuery"]
    assert "กำลังทำ pack" in answer["text"] and len(bot) == before
    assert state["clip_wait"]["sources"] == ["flow", "pexels", "pexels"]


def test_tapping_the_ticked_character_does_not_replan(bot, monkeypatch):
    state = review_state()
    run(main.on_studio(None, state))
    calls = capture_api(monkeypatch)
    boards = len([item for item in bot if item[0] == "board"])
    asyncio.run(main.on_callback(None, state, a_tap(f"stc:{CLIP}:auto")))
    assert not SPAWNED and len([item for item in bot if item[0] == "board"]) == boards
    (answer,) = [p for m, p in calls if m == "answerCallbackQuery"]
    assert "อยู่แล้ว" in answer["text"]


def test_the_pack_message_says_numbers_are_cards(bot):
    state = review_state()
    run(main.on_studio(None, state))
    message = next(item for item in bot if item[0] == "say" and "Studio pack" in item[1])
    assert "ปุ่มเลข = การ์ด" in message[1]


def test_speak_toggle_plans_one_shot_per_card_with_a_10s_shot_for_long_cards(bot, monkeypatch):
    state = review_state()
    run(main.on_studio(None, state))
    state["clip_wait"]["sources"] = ["flow", "flow", "pexels"]
    run(main.on_studio_callback(None, state, f"sts:{CLIP}"))
    wait = state["clip_wait"]
    assert wait["speak"] is True
    assert [item for item in bot if item[0] == "board"][-1][1]["speak"] is True
    pack = studio.read_pack(CLIP)
    # spans 7.0 / 9.0: both over the 8s budget, card 2 past 10s too.
    assert pack["shots"] == {"0": 1, "1": 1} and pack["seconds"] == {"0": 10.0, "1": 10.0}
    assert pack["length"] == 20.0 and pack["speak"] is True
    assert pack["scenes"][0]["animate"] == (
        'Speaks in Thai: "พูด 0" Natural lip movement. slow push in. '
        "No subtitles, no on-screen text, no background music.")
    message = [item for item in bot if item[0] == "say" and "Studio pack" in item[1]][-1][1]
    assert "🗣" in message and "ตั้ง shot 10 วิ" in message and "การ์ด 2 ยาวเกิน 10 วิ" in message
    doc = [item for item in bot if item[0] == "doc"][-1][1]
    assert 'DIALOGUE (Thai): "พูด 0"' in doc and "10 seconds." in doc and "No dialogue" not in doc
    version = wait["versions"][pack["token"]]
    assert version["speak"] is True and version["seconds"] == {"0": 10.0, "1": 10.0}


def test_speak_needs_a_character(bot, monkeypatch):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stc:{CLIP}:none"))
    calls = capture_api(monkeypatch)
    asyncio.run(main.on_callback(None, state, a_tap(f"sts:{CLIP}")))
    assert state["clip_wait"]["speak"] is False and not SPAWNED
    assert "เลือกตัวละครก่อน" in next(p for m, p in calls if m == "answerCallbackQuery")["text"]


def test_speaking_export_keeps_voice_and_renders_with_a_spliced_take(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: (pathlib.Path("take.wav"), [0.0, 7.0, 16.0]))
    spliced = []

    def take(clip_id, sources, audio, starts):
        spliced.append((sources, starts))
        return pathlib.Path("spliced.wav"), [0.0, 9.5, 18.0]

    monkeypatch.setattr(studio, "speaking_take", take)
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"sts:{CLIP}"))
    token = studio.read_pack(CLIP)["token"]
    inbox = studio.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{token}.mp4.taken"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=24:duration=10",
                    "-f", "lavfi", "-i", "sine=duration=10", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-f", "mp4", str(path)],
                   check=True, capture_output=True)
    asyncio.run(main.process_export(None, state, token, path))
    assert studio.voice_path(CLIP, 0).is_file()
    assert spliced == [(["flow", "pexels", "pexels"], [0.0, 7.0, 16.0])]
    assert calls and calls[0]["narration"] == (pathlib.Path("spliced.wav"), [0.0, 9.5, 18.0])
