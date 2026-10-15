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
