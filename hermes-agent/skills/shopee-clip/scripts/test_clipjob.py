"""Unit tests for clipjob.py's state machine and gates (no ffmpeg, no Telegram).

Run: uv run --with pytest pytest -q hermes-agent/skills/shopee-clip/scripts/test_clipjob.py
"""
import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("clipjob", os.path.join(HERE, "clipjob.py"))
cj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cj)


def job(shots=3, mode="presenter", prod=None):
    j = cj.new_job("t-1", mode, "Thing", "https://s.shopee.co.th/x", shots, ["/tmp/ref.jpg"], character="น้องมุก")
    if prod:
        cj.set_production(j, prod)
    return j


def render(j, k, t):
    """Drive shot k from pending to in_review in auto mode."""
    cj.reserve(j, k, None, t)
    cj.submitted(j, k, f"edit-{k}", 12)
    cj.mark_ready(j, k, f"/tmp/s{k}.mp4", {"probe": {"ok": True}})


# ---------------------------------------------------------------- creation
def test_flow_mode_needs_shots_and_ref():
    with pytest.raises(cj.Refused):
        cj.new_job("a", "presenter", "x", shots=0, refs=["r"])
    with pytest.raises(cj.Refused):
        cj.new_job("a", "product", "x", shots=3, refs=[])
    assert cj.new_job("a", "gameplay", "x")["shots"] == []


def test_presenter_needs_character():
    with pytest.raises(cj.Refused, match="character"):
        cj.new_job("a", "presenter", "x", shots=1, refs=["r"])
    assert cj.new_job("a", "product", "x", shots=1, refs=["r"])["character"] is None


def test_flags_need_fix_decision():
    j = approved_job()
    rep = {"flags": ["scene1: Flow said 'xx' @3.1-3.6s not in script",
                     "no CTA pill in final scene -> auto-added 'Link below!' 6.0-8.2"], "v_dur": 8, "a_dur": 8}
    gfx = {"headlines": [{"text": "x"}]}
    probs = cj.deliver_problems(j, rep, gfx, "#a", [])
    assert len(probs) == 1 and "not decided" in probs[0] and "auto-added" not in probs[0]
    acks = cj.parse_acks(["not in script=Fix: ส่งแบบนี้ได้"])
    assert cj.deliver_problems(j, rep, gfx, "#a", acks) == []
    with pytest.raises(cj.Refused):
        cj.parse_acks(["no reason given"])


def test_bad_slug_and_mode():
    with pytest.raises(cj.Refused):
        cj.new_job("Bad Slug", "presenter", "x", shots=1, refs=["r"])
    with pytest.raises(cj.Refused):
        cj.new_job("a", "talking-head", "x", shots=1, refs=["r"])


# ---------------------------------------------------------------- auto mode
def test_reserve_needs_auto_production():
    j = job(prod="prompt")
    with pytest.raises(cj.Refused, match="auto production only"):
        cj.reserve(j, 1, None, 1000)


def test_pacing_and_chaining():
    j = job(prod="auto")
    t = cj.reserve(j, 1, None, 1000)
    cj.submitted(j, 1, "e1")
    with pytest.raises(cj.Refused, match="has not rendered"):
        cj.reserve(j, 2, t, 2000)
    cj.mark_ready(j, 1, "/tmp/s1.mp4", {"probe": {"ok": True}, "frame": {"ok": False, "note": "drift"}})
    with pytest.raises(cj.Refused, match="failed gate"):       # baan-toyshelf 2026-11-11: shot 2 fired anyway
        cj.reserve(j, 2, t, t + 300)
    cj.shot(j, 1)["gates"] = {"probe": {"ok": True}}
    with pytest.raises(cj.Pacing) as p:
        cj.reserve(j, 2, t, t + 100)
    assert p.value.wait_s == 201
    cj.reserve(j, 2, t, t + 300)
    assert cj.shot(j, 2)["state"] == "submitting"


def test_rendered_shot_needs_regen_before_resubmit():
    j = job(prod="auto")
    render(j, 1, 1000)
    with pytest.raises(cj.Refused, match="needs Fix"):
        cj.reserve(j, 1, None, 5000)
    cj.decide(j, 1, "regen")
    cj.reserve(j, 1, None, 5000)
    assert len(cj.shot(j, 1)["attempts"]) == 2


def test_unusual_activity_triggers_fallback_immediately():
    j = job(prod="auto")
    cj.reserve(j, 1, None, 1000)
    assert cj.submit_failed(j, 1, "Failed: We noticed some unusual activity") is True
    assert cj.shot(j, 1)["state"] == "pending"


def test_second_failure_triggers_fallback():
    j = job(prod="auto")
    cj.reserve(j, 1, None, 1000)
    assert cj.submit_failed(j, 1, "no credits?") is False
    cj.reserve(j, 1, None, 2000)
    assert cj.submit_failed(j, 1, "button vanished") is True


def test_trouble_second_hit_on_same_step():
    j = job(prod="auto")
    assert cj.trouble(j, "picker", "overlay empty") is False
    assert cj.trouble(j, "cdp", "screenshot timeout") is False
    assert cj.trouble(j, "picker", "overlay empty again") is True


def test_fallback_never_repacks_paid_shots():
    j = job(shots=4, prod="auto")
    render(j, 1, 1000)                      # paid, in review
    cj.reserve(j, 2, None, 2000)
    cj.submitted(j, 2, "e2", 12)            # paid, still rendering
    j["shots"][2]["state"] = "submitting"   # reserved, never confirmed sent -> back to pending
    j["shots"][2]["attempts"].append({"via": "auto", "reserved_at": "x"})
    todo = cj.fallback(j, "unusual activity")
    assert todo == [3, 4]
    assert j["production"] == "prompt"
    assert j["fallback"]["credits_spent_shots"] == [1, 2]
    assert j["fallback"]["in_flight"] == [2]
    assert cj.pack_targets(j) == [3, 4]
    with pytest.raises(cj.Refused, match=r"cannot take a file|already has a file"):
        cj.ingest(j, 1, "/tmp/x.mp4")


def test_cannot_go_back_to_auto_after_fallback():
    j = job(prod="auto")
    cj.fallback(j, "x")
    with pytest.raises(cj.Refused):
        cj.set_production(j, "auto")


# ---------------------------------------------------------------- prompt pack
def test_pack_needs_prompt_production():
    with pytest.raises(cj.Refused, match="production=prompt"):
        cj.pack_targets(job(prod="auto"))


def test_tag_round_trip_and_ingest_flow():
    j = job(shots=2, prod="prompt")
    text = f"{cj.shot_tag('t-1', 2)} ช็อต 2/2 · 9:16\nreply ข้อความนี้"
    assert cj.parse_tag(text) == ("t-1", 2)
    assert cj.parse_tag("random caption") is None
    j["shots"][1]["state"] = "packed"
    dst = cj.ingest(j, 2, "/tmp/s2.mp4")
    assert dst.startswith(j["workdir"] + "/") and dst.endswith("shot2_a1.mp4")
    assert cj.shot(j, 2)["state"] == "submitted"
    cj.mark_ready(j, 2, "/tmp/s2.mp4", {"probe": {"ok": True}})
    with pytest.raises(cj.Refused, match="already has a file"):
        cj.ingest(j, 2, "/tmp/s2b.mp4")
    cj.decide(j, 2, "regen")
    cj.ingest(j, 2, "/tmp/s2b.mp4")
    assert [a["via"] for a in cj.shot(j, 2)["attempts"]] == ["prompt", "prompt"]


def test_default_workdir_is_durable():
    j = cj.new_job("w-1", "product", "x", shots=1, refs=["r"])
    assert j["workdir"].startswith(cj.WORK) and "scratch" not in j["workdir"]


def test_long_prompt_splits_and_every_part_is_tagged():
    short = cj.prompt_messages("t-1", 1, 2, "สั้น <b>", 10)
    assert len(short) == 1 and "&lt;b&gt;" in short[0] and "reply" in short[0]
    long = cj.prompt_messages("t-1", 2, 2, "ก" * 8000, 10, "\nเฟรมเริ่ม: x")
    assert len(long) == 3
    assert all(cj.parse_tag(m) == ("t-1", 2) and len(m) <= 4096 for m in long)
    assert "ส่วน 1/3" in long[0] and "reply" in long[0] and "reply" not in long[1]


def test_probe_verdict_flags_telegram_reencode():
    ok = cj.probe_verdict({"w": 720, "h": 1280, "dur": 8.0, "kbps": 4000, "vcodec": "h264", "has_audio": True})
    assert ok["ok"]
    small = cj.probe_verdict({"w": 480, "h": 854, "dur": 8.0, "kbps": 900, "vcodec": "h264", "has_audio": True})
    assert not small["ok"] and "ส่งแบบไฟล์" in small["note"]
    landscape = cj.probe_verdict({"w": 1280, "h": 720, "dur": 8.0, "kbps": 4000, "vcodec": "h264", "has_audio": True})
    assert not landscape["ok"]
    assert not cj.probe_verdict(None)["ok"]


# ---------------------------------------------------------------- review + assembly
def test_decision_text():
    assert cj.parse_decision_text("✅ ผ่าน ช็อต 2 · t-1") == ("t-1", 2, "approve")
    assert cj.parse_decision_text("🔁 gen ใหม่ ช็อต 3 · t-1") == ("t-1", 3, "regen")
    assert cj.parse_decision_text("ok") is None


def test_assemble_only_when_all_approved():
    j = job(shots=2, prod="auto")
    render(j, 1, 1000)
    cj.decide(j, 1, "approve")
    with pytest.raises(cj.Refused, match="2:pending"):
        cj.assemble_files(j)
    render(j, 2, 2000)
    cj.decide(j, 2, "approve")
    assert cj.assemble_files(j) == ["/tmp/s1.mp4", "/tmp/s2.mp4"]


def test_cta_patterns_catch_asr_spelling():
    assert "ใต้คลิป" in cj.cta_hits("ลิ้งอยู่ต้ายคลิป")
    assert cj.cta_hits("สีสวยมาก ใช้ง่าย") == []


def test_frame_arg():
    assert cj.parse_frame("pass")["ok"]
    assert not cj.parse_frame("flag:text on screen")["ok"]
    with pytest.raises(cj.Refused):
        cj.parse_frame("looks fine")


# ---------------------------------------------------------------- delivery gate
def approved_job(mode="presenter"):
    j = job(shots=1, mode=mode, prod="auto")
    render(j, 1, 1000)
    cj.decide(j, 1, "approve")
    return j


def test_deliver_gate_clean():
    j = approved_job()
    assert cj.deliver_problems(j, {"flags": [], "v_dur": 8.0, "a_dur": 8.0},
                               {"headlines": [{"text": "x"}]}, "#a #b") == []


def test_deliver_gate_blocks():
    j = job(shots=2, prod="auto")
    probs = cj.deliver_problems(j, {"flags": ["scene1: phrase SKIPPED"], "v_dur": 8, "a_dur": 9},
                                {}, "#ลด50% " + "#x" * 80)
    text = " ".join(probs)
    for needle in ("not approved", "graphics plan is empty", "FLAG", "audio", "150", "price"):
        assert needle in text, needle


def test_hashtags_gate():
    assert cj.hashtag_problems("#ของดี #ShopeeTH") == []
    assert cj.hashtag_problems("#好物")
    assert cj.hashtag_problems("#ราคาดี")


def test_gameplay_skips_shot_gates_but_not_hashtags():
    j = cj.new_job("g-1", "gameplay", "Game", "https://s.shopee.co.th/x")
    assert cj.deliver_problems(j, {"flags": []}, {}, "#game") == []
    assert cj.deliver_problems(j, {"flags": []}, {}, "#เกม #好")


# ---------------------------------------------------------------- CLI smoke (state on disk)
def test_cli_new_status_cancel(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    ref = tmp_path / "ref.jpg"; ref.write_bytes(b"x")
    wd = tmp_path / "wd"
    assert cj.main(["new", "c-1", "--mode", "product", "--product", "P", "--link", "https://s.shopee.co.th/a",
                    "--shots", "2", "--ref", str(ref), "--workdir", str(wd)]) == 0
    assert cj.main(["new", "c-1", "--mode", "product", "--product", "P", "--shots", "2", "--ref", str(ref)]) == 1
    assert cj.main(["production", "c-1", "prompt"]) == 0
    assert cj.main(["pack", "c-1", "--no-send"]) == 1          # prompt files missing
    (wd / "shot1.txt").write_text("prompt one"); (wd / "shot2.txt").write_text("prompt two")
    assert cj.main(["pack", "c-1", "--no-send"]) == 0
    assert cj.main(["ingest", "c-1", str(ref), "--reply-text", "no tag here"]) == 1
    assert cj.main(["ingest", "c-1", str(ref), "--reply-text", "[ช็อต 2 · c-1] ช็อต 2/2"]) == 0
    saved = json.load(open(tmp_path / "jobs" / "c-1.json"))
    assert [s["state"] for s in saved["shots"]] == ["packed", "submitted"]
    kept = saved["shots"][1]["attempts"][-1]["file_in"]
    assert kept == str(wd / "shot2_a1.jpg") and (wd / "shot2_a1.jpg").exists()
    assert cj.main(["cancel", "c-1", "--reason", "test"]) == 0
    assert cj.main(["reserve", "c-1", "1"]) == 1


# ---------------------------------------------------------------- 2026-11-11 hardening
def test_failed_gate_shot_unblocks_next_once_fix_approves():
    j = job(prod="auto")
    cj.reserve(j, 1, None, 1000); cj.submitted(j, 1)
    cj.mark_ready(j, 1, "/tmp/s1.mp4", {"frame": {"ok": False, "note": "x"}})
    cj.decide(j, 1, "approve")
    cj.reserve(j, 2, None, 5000)


def test_placeholder_edit_id_is_not_an_id():
    j = job(prod="auto")
    cj.reserve(j, 1, None, 1000)
    cj.submitted(j, 1, "pending-shot1", 15)
    assert cj.shot(j, 1)["attempts"][-1]["edit_id"] is None
    with pytest.raises(cj.Refused, match="placeholder"):
        cj.set_edit_id(j, 1, "pending-x")
    cj.set_edit_id(j, 1, "abc123")
    assert cj.shot(j, 1)["attempts"][-1]["edit_id"] == "abc123"


def test_regen_drops_the_next_shots_unsent_reservation():
    j = job(prod="auto")
    render(j, 1, 1000)
    cj.reserve(j, 2, None, 5000)
    assert cj.decide(j, 1, "regen") == {"shot": 2, "state": "pending", "ask": False}
    assert cj.shot(j, 2)["state"] == "pending"


def test_regen_flags_a_rendered_next_shot_and_fix_decides():
    j = job(shots=2, prod="auto")
    render(j, 1, 1000); render(j, 2, 5000)
    cj.decide(j, 2, "approve")
    st = cj.decide(j, 1, "regen")
    assert st == {"shot": 2, "state": "approved", "ask": True}
    cj.reserve(j, 1, None, 9000); cj.submitted(j, 1)
    cj.mark_ready(j, 1, "/tmp/s1b.mp4", {"probe": {"ok": True}}); cj.decide(j, 1, "approve")
    with pytest.raises(cj.Refused, match="keep/regen"):
        cj.assemble_files(j)
    assert any("keep/regen" in p for p in cj.deliver_problems(j, {}, {"headlines": [1]}, "#a"))
    cj.decide(j, 2, "approve")                 # keep it
    assert cj.assemble_files(j) == ["/tmp/s1b.mp4", "/tmp/s2.mp4"]
    # the other choice: regenerate the stale shot although it was approved
    j2 = job(shots=2, prod="auto")
    render(j2, 1, 1000); render(j2, 2, 5000); cj.decide(j2, 2, "approve"); cj.decide(j2, 1, "regen")
    cj.decide(j2, 2, "regen")
    assert cj.shot(j2, 2)["state"] == "regen_approved" and "chain_stale" not in cj.shot(j2, 2)


def test_stale_shot_still_rendering_is_flagged_at_review():
    j = job(shots=2, prod="auto")
    render(j, 1, 1000)
    cj.reserve(j, 2, None, 5000); cj.submitted(j, 2)
    assert cj.decide(j, 1, "regen") == {"shot": 2, "state": "submitted", "ask": False}
    cj.mark_ready(j, 2, "/tmp/s2.mp4", {"probe": {"ok": True}})
    assert cj.shot(j, 2)["chain_stale"] == "review"


def test_approved_shot_without_stale_chain_cannot_be_regenerated():
    j = job(shots=1, prod="auto")
    render(j, 1, 1000); cj.decide(j, 1, "approve")
    with pytest.raises(cj.Refused):
        cj.decide(j, 1, "regen")


def test_failed_paid_shot_can_be_regenerated_by_fix():
    j = job(prod="auto")
    cj.reserve(j, 1, None, 1000); cj.submitted(j, 1)
    cj.submit_failed(j, 1, "Failed card", credits_spent=True)
    assert cj.shot(j, 1)["state"] == "failed"
    assert cj.review_keyboard("t-1", 1, approve=False)["keyboard"] == [[{"text": "🔁 gen ใหม่ ช็อต 1 · t-1"}]]
    assert cj.parse_decision_text("🔁 gen ใหม่ ช็อต 1 · t-1") == ("t-1", 1, "regen")
    cj.decide(j, 1, "regen")
    cj.reserve(j, 1, None, 9000)


def test_cli_ready_keeps_state_when_send_fails_then_resend(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    j = job(shots=1, mode="product", prod="prompt"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "prompt"})
    cj.save(j)
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    calls = []
    monkeypatch.setattr(cj, "run", lambda cmd: (calls.append(cmd) or ((1, "", "boom") if len(calls) == 1 else (0, "", ""))))
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass"]) == 1
    assert "--resend" in capsys.readouterr().err
    assert cj.load("t-1")["shots"][0]["state"] == "in_review"
    assert cj.main(["ready", "t-1", "1", "--resend"]) == 0
    assert cj.load("t-1")["shots"][0].get("review_sent")


def test_cli_gameplay_job_note_deliver_reopen(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    log = tmp_path / "clip-log.jsonl"; monkeypatch.setattr(cj, "CLIP_LOG", str(log))
    assert cj.main(["new", "g-1", "--mode", "gameplay", "--product", "Game", "--link", "https://s.shopee.co.th/x",
                    "--workdir", str(tmp_path / "w")]) == 0
    assert cj.main(["note", "g-1", "vo done; next: build_v5"]) == 0
    assert "vo done" in json.dumps(cj.load("g-1")["events"], ensure_ascii=False)
    final = tmp_path / "f.mp4"; final.write_bytes(b"a"); cover = tmp_path / "c.jpg"; cover.write_bytes(b"c")
    monkeypatch.setattr(cj, "av_durations", lambda p: (20.0, 20.0))
    monkeypatch.setattr(cj, "run", lambda cmd: (0, json.dumps({"ok": True}), ""))
    args = ["deliver", "g-1", "--final", str(final), "--hashtags", "#game", "--cover", str(cover), "--caption", "c",
            "--hook-id", "gph-1", "--category", "game"]
    assert cj.main(args) == 0
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["style"] == "gameplay" and row["credits"] == 0 and row["duration_s"] == 20.0 and row["edit_id"] is None
    assert cj.main(args) == 1                                   # delivered: closed
    assert cj.main(["reopen", "g-1", "--reason", "ฟิก: ซับทับ sticker"]) == 0
    final.write_bytes(b"b")
    assert cj.main(args) == 0
    rows = log.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2 and json.loads(rows[1])["notes"].startswith("REVISED: ฟิก")


def test_flow_mode_still_needs_a_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    j = job(shots=1, mode="product", prod="prompt"); cj.save(j)
    assert cj.main(["deliver", "t-1", "--final", "/nope.mp4", "--hashtags", "#a", "--cover", "/c.jpg", "--caption", "c"]) == 1
    assert "--report" in capsys.readouterr().err


def test_old_job_files_still_load(tmp_path, monkeypatch, capsys):
    """Jobs written before the hardening (placeholder edit ids, no chain_stale/review_sent keys)."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    j = job(shots=2, prod="auto")
    render(j, 1, 1000); j["shots"][0]["attempts"][-1]["edit_id"] = "pending-shot1"
    cj.save(j)
    assert cj.main(["status", "t-1"]) == 0 and cj.main(["decide", "t-1", "1", "approve"]) == 0
    assert cj.main(["edit-id", "t-1", "1", "real-id-9"]) == 0
    assert cj.load("t-1")["shots"][0]["attempts"][-1]["edit_id"] == "real-id-9"
