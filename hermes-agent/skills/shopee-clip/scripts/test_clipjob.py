"""Unit tests for clipjob.py's state machine and gates (no ffmpeg, no Telegram).

Run: uv run --with pytest pytest -q hermes-agent/skills/shopee-clip/scripts/test_clipjob.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("clipjob", os.path.join(HERE, "clipjob.py"))
cj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cj)
cj.FINALS_DIR = tempfile.mkdtemp(prefix="clipjob-finals-")
cj.HERMES_DB = "/nonexistent/state.db"                          # no test reads the real Hermes sessions     # no test writes into the real kept-finals dir
os.environ["CLIPJOB_NO_TIMER"] = "1"                            # no test leaves a 5-minute close sleeper behind
cj.DOWNLOADS = []                                               # nor deletes from the real Downloads dirs
cj.DIR = tempfile.mkdtemp(prefix="clipjob-jobs-")               # main() sweeps DIR: never the real jobs dir
cj.WORK = tempfile.mkdtemp(prefix="clipjob-work-")
cj.GATEWAY_PID = os.path.join(cj.WORK, "no-gateway.pid")            # never adopt the real gateway env
cj.has_face = lambda img: True                                  # no test runs OpenCV; face tests override it
cj.PLATE_TRIAL = False                                          # the plate tests switch it back on
cj.prod_check = lambda raw, refs, out: {"verdict": "no-match"}  # no test runs OpenCV; prodcheck tests override it


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


def test_switch_to_auto_unpacked_shots_can_reserve():
    """Fix orders auto after the prompt pack went out (wellux-swatter-666 2026-11-22):
    set_production('auto') must return packed shots to pending, or reserve() refuses them."""
    j = job(prod="auto")
    cj.shot(j, 1)["state"] = "packed"          # the state a pack leaves behind
    with pytest.raises(cj.Refused, match="packed"):
        cj.reserve(j, 1, None, 1000)
    cj.set_production(j, "auto")               # re-running it un-packs (production was already auto)
    assert cj.shot(j, 1)["state"] == "pending"
    cj.reserve(j, 1, None, 1000)
    assert cj.shot(j, 1)["state"] == "submitting"


def test_plate_trial_gates_shot_1_of_an_auto_presenter(tmp_path, monkeypatch, capsys):
    """cal-d-protein-1mo 2026-11-25 was the trial order (🤖 🧑): the pointer was read, scene-plate.md never
    opened, nothing logged. reserve shot 1 now waits for a plate verdict."""
    monkeypatch.setattr(cj, "PLATE_TRIAL", True)
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(prod="auto")
    j["workdir"] = str(tmp_path / "w"); os.makedirs(j["workdir"])
    with pytest.raises(cj.Refused, match="scene-plate"):
        cj.reserve(j, 1, None, 1000)
    cj.save(j)
    assert cj.main(["plate", "t-1", "used"]) == 1                      # no plate.jpg yet
    open(os.path.join(j["workdir"], "plate.jpg"), "wb").write(b"x")
    assert cj.main(["plate", "t-1", "used"]) == 0
    j = cj.load("t-1")
    assert j["plate"]["state"] == "used"
    cj.reserve(j, 1, None, 1000)
    assert cj.shot(j, 1)["state"] == "submitting"


def test_plate_skip_needs_a_reason_and_other_modes_are_not_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "PLATE_TRIAL", True)
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(prod="auto"); cj.save(j)
    assert cj.main(["plate", "t-1", "skipped"]) == 1
    assert cj.main(["plate", "t-1", "skipped", "--why", "Image tab read 4 credits"]) == 0
    cj.reserve(cj.load("t-1"), 1, None, 1000)
    p = cj.new_job("p-1", "product", "Thing", "", 1, ["/tmp/ref.jpg"])   # 📦 skips the trial
    cj.set_production(p, "auto")
    cj.reserve(p, 1, None, 1000)


def test_plate_trial_ends_after_one_delivered_plate(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "PLATE_TRIAL", True)
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    done = job(prod="auto"); done["job"] = "done-1"; done["status"] = "delivered"
    done["plate"] = {"state": "used"}; cj.save(done)
    j = job(prod="auto")
    cj.reserve(j, 1, None, 1000)                                       # Fix's verdict decides from here


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
    assert cj.main(["new", "c-1", "--mode", "product", "--product", "P", "--shots", "2", "--ref", str(ref)]) == 1
    assert "no storyboard on record" in capsys.readouterr().err      # a Flow job needs intake + board first
    assert cj.main(["intake", "c-1", "--product", "P", "--workdir", str(wd)]) == 0
    assert cj.main(["board", "c-1", "--hook-id", "home-2"]) == 0                             # no state.db in tests: reply unverified
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
    j = job(shots=1, mode="product", prod="auto"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "auto"})
    cj.save(j)
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    calls = []
    monkeypatch.setattr(cj, "run", lambda cmd: (calls.append(cmd) or ((1, "", "boom") if len(calls) == 1 else (0, "", ""))))
    j = cj.load("t-1"); cj.shot(j, 1)["idcheck"] = {"sig": cj.file_sig(str(raw))}; cj.save(j)
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--identity", "match"]) == 1
    assert "--resend" in capsys.readouterr().err
    assert cj.load("t-1")["shots"][0]["state"] == "in_review"
    assert cj.main(["ready", "t-1", "1", "--resend"]) == 0
    assert cj.load("t-1")["shots"][0].get("review_sent")


def test_cli_gameplay_job_note_deliver_reopen(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    monkeypatch.setattr(cj, "FINALS_DIR", str(tmp_path / "finals"))
    log = tmp_path / "clip-log.jsonl"; monkeypatch.setattr(cj, "CLIP_LOG", str(log))
    assert cj.main(["new", "g-1", "--mode", "gameplay", "--product", "Game", "--link", "https://s.shopee.co.th/x",
                    "--workdir", str(tmp_path / "w")]) == 0
    assert cj.main(["note", "g-1", "vo done; next: build_v5"]) == 0
    assert "vo done" in json.dumps(cj.load("g-1")["events"], ensure_ascii=False)
    final = tmp_path / "f.mp4"; final.write_bytes(b"a"); cover = tmp_path / "c.jpg"; cover.write_bytes(b"c")
    monkeypatch.setattr(cj, "av_durations", lambda p: (20.0, 20.0))
    monkeypatch.setattr(cj, "run", lambda cmd: (0, json.dumps({"ok": True}), ""))
    args = ["deliver", "g-1", "--final", str(final), "--hashtags", "#game", "--cover", str(cover), "--caption", "c",
            "--hook-id", "gph-1", "--category", "game", "--post-hook", "ใครเล่นเกมนี้จบแล้วต้องลองโหมดใหม่"]
    assert cj.main(args) == 0
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["style"] == "gameplay" and row["credits"] == 0 and row["duration_s"] == 20.0 and row["edit_id"] is None
    kept = cj.load("g-1")["delivery"]["kept"]
    assert [os.path.basename(k) for k in kept] == ["g-1.mp4", "g-1_cover.jpg"] and all(os.path.exists(k) for k in kept)
    assert cj.main(args) == 1                                   # delivered: closed
    assert cj.main(["reopen", "g-1", "--reason", "ฟิก: ซับทับ sticker"]) == 0
    final.write_bytes(b"b")
    assert cj.main(args) == 0
    rows = log.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2 and json.loads(rows[1])["notes"].startswith("REVISED: ฟิก")
    assert cj.main(["reopen", "g-1", "--reason", "product film"]) == 0
    final.write_bytes(b"c")
    assert cj.main(args + ["--style", "footage"]) == 0
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["style"] == "footage"


def test_flow_mode_still_needs_a_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    j = job(shots=1, mode="product", prod="prompt"); cj.save(j)
    assert cj.main(["deliver", "t-1", "--final", "/nope.mp4", "--hashtags", "#a", "--cover", "/c.jpg", "--caption", "c"]) == 1
    assert "--report" in capsys.readouterr().err


def test_hands_mode_is_a_flow_mode_with_no_presenter_gates(tmp_path, monkeypatch, capsys):
    """✋ = the 📦 pipeline with hands in frame: refs and graphics required, no character, VO added in post."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    with pytest.raises(cj.Refused, match="photo"):
        cj.new_job("h", "hands", "x", shots=1, refs=[])
    j = cj.new_job("t-1", "hands", "Thing", "https://s.shopee.co.th/x", 1, ["/tmp/ref.jpg"])
    assert j["character"] is None and len(j["shots"]) == 1
    j["production"] = "auto"; j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "auto"})
    cj.save(j)
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": False})

    def no_asr(*a):
        raise AssertionError("the repeats gate is for a presenter speaking in Flow")
    monkeypatch.setattr(cj, "repeats_gate", no_asr)
    # a 3-frame check passed a face that was on screen for <1 s (aimi-rack, 2026-11-13): ready needs the 0.5 s scan
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--no-send"]) == 1
    assert "scan" in capsys.readouterr().err

    def fake_sheets(video, prefix):
        (tmp_path / "shot1_scan1.jpg").write_bytes(b"j")
        return [str(tmp_path / "shot1_scan1.jpg")]
    monkeypatch.setattr(cj, "scan_sheets", fake_sheets)
    assert cj.main(["scan", "t-1", "1", "--raw", str(raw)]) == 0
    assert "face" in capsys.readouterr().out
    raw.write_bytes(b"a regenerated file")                       # the scan was of the old render
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--no-send"]) == 1
    assert cj.main(["scan", "t-1", "1", "--raw", str(raw)]) == 0
    monkeypatch.setattr(cj, "id_sheet", lambda raw, refs, out, dur: (open(out, "wb").close() or out, [0.5, 9.9]))
    assert cj.main(["idcheck", "t-1", "1", "--raw", str(raw)]) == 0
    capsys.readouterr()
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--identity", "match", "--no-send"]) == 0
    j = cj.load("t-1")
    assert set(j["shots"][0]["gates"]) == {"probe", "frame", "identity"}   # a silent shot is fine: no speech asked
    cj.decide(j, 1, "approve")
    probs = cj.deliver_problems(j, {"v_dur": 10, "a_dur": 10}, {}, "#a", [])
    assert any("graphics" in p for p in probs)


def test_old_job_files_still_load(tmp_path, monkeypatch, capsys):
    """Jobs written before the hardening (placeholder edit ids, no chain_stale/review_sent keys)."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    j = job(shots=2, prod="auto")
    render(j, 1, 1000); j["shots"][0]["attempts"][-1]["edit_id"] = "pending-shot1"
    cj.save(j)
    assert cj.main(["status", "t-1"]) == 0 and cj.main(["decide", "t-1", "1", "approve"]) == 0
    assert cj.main(["edit-id", "t-1", "1", "real-id-9"]) == 0
    assert cj.load("t-1")["shots"][0]["attempts"][-1]["edit_id"] == "real-id-9"


# ---------------------------------------------------------------- timing
def _ev(j, hhmm, msg):
    j["events"].append({"ts": f"2026-11-12T{hhmm}:00+07:00", "msg": msg})


def test_timeline_splits_prep_generation_and_post():
    j = job(shots=1)
    j["started"], j["created"], j["events"] = "2026-11-12T08:55:00+07:00", "2026-11-12T10:31:00+07:00", []
    for hhmm, msg in [("10:31", "created"), ("11:15", "ready shot 1 pass=True"), ("11:23", "decide shot 1: approve"),
                      ("12:18", "delivered")]:
        _ev(j, hhmm, msg)
    tl = cj.timeline(j)
    assert tl == {"total_min": 203, "stages": [["เตรียม", 96], ["gen+รีวิว", 52], ["post", 55]], "wait_fix_min": 8}
    text = cj.timeline_text(tl)
    assert "รวม 3 ชม. 23 น." in text and "รอฟิกตอบ 8 น." in text


def test_timeline_gameplay_and_revision():
    j = job(shots=0, mode="gameplay")
    j["created"], j["events"] = "2026-11-12T10:00:00+07:00", []
    j.pop("started", None)                              # an old job file has no start stamp
    _ev(j, "10:00", "created"); _ev(j, "10:40", "delivered")
    assert cj.timeline(j)["stages"] == [["เตรียม", 0], ["ทำคลิป", 40]]
    _ev(j, "13:00", "reopened for a revision: sub typo"); _ev(j, "13:12", "delivered")
    assert cj.timeline(j) == {"total_min": 12, "stages": [["แก้งาน", 12]], "wait_fix_min": 0}


def test_workdir_started_uses_the_oldest_file(tmp_path):
    f = tmp_path / "intake_sheet.jpg"
    f.write_bytes(b"x")
    os.utime(f, (1000, 1000))
    assert cj.workdir_started(str(tmp_path), 5000) == 1000
    assert cj.workdir_started(str(tmp_path / "none"), 5000) == 5000


def test_workdir_started_ignores_files_older_than_the_lookback(tmp_path):
    """gta6-codebox-gp2 2026-11-25: the image of an order Fix cancelled at 20:14 sat in the workdir; the real order
    came at 23:06, intake at 23:10, and the job's clock started at 20:15 (+3 h in the total and in เตรียม)."""
    old, fresh = tmp_path / "img2.jpg", tmp_path / "img1.jpg"
    old.write_bytes(b"x"); fresh.write_bytes(b"x")
    os.utime(old, (1000, 1000)); os.utime(fresh, (20000, 20000))
    assert cj.workdir_started(str(tmp_path), 20600, lookback=cj.INTAKE_LOOKBACK_S) == 20000
    old2 = tmp_path / "copied_source.mp4"                 # copy2 keeps a days-old mtime
    old2.write_bytes(b"x"); os.utime(old2, (5, 5))
    assert cj.workdir_started(str(tmp_path), 20600, lookback=cj.INTAKE_LOOKBACK_S) == 20000
    assert cj.workdir_started(str(tmp_path), 20600) == 5    # no lookback: unchanged behaviour


def test_cli_intake_clock_skips_a_cancelled_orders_file(tmp_path, monkeypatch):
    wd = tmp_path / "w"; wd.mkdir()
    stale = wd / "img2.jpg"; stale.write_bytes(b"x")
    t0 = cj.now()
    os.utime(stale, (t0 - 3 * 3600, t0 - 3 * 3600))
    fresh = wd / "intake_sheet.jpg"; fresh.write_bytes(b"x")
    os.utime(fresh, (t0 - 240, t0 - 240))
    assert cj.main(["intake", "clk-1", "--product", "P", "--workdir", str(wd)]) == 0
    j = cj.load("clk-1")
    assert abs(cj._epoch(j["started"]) - (t0 - 240)) < 5


def test_billed_credits_skip_a_refunded_failed_card():
    j = {"shots": [{"attempts": [{"submitted_at": "t", "credits": 15}]},
                   {"attempts": [{"submitted_at": "t", "credits": 15, "failed": "policy (refunded)", "credits_spent": False},
                                 {"submitted_at": "t", "credits": 15, "failed": "bad card", "credits_spent": True},
                                 {"submitted_at": "t", "credits": 15},
                                 {"reserved_at": "t"}]}]}
    assert cj.billed_credits(j) == [15, 15, 15]


def test_timeline_counts_waits_on_fix_in_a_footage_job():
    j = job(shots=0, mode="gameplay")
    j["created"], j["events"] = "2026-11-12T02:00:00+07:00", []
    j.pop("started", None)
    for hhmm, msg in [("02:00", "created"), ("04:16", "wait: turn budget used up, footage picked"),
                      ("06:53", "note: resumed"), ("11:04", "delivered")]:
        _ev(j, hhmm, msg)
    tl = cj.timeline(j)
    assert tl["wait_fix_min"] == 157 and tl["stages"] == [["เตรียม", 0], ["ทำคลิป", 544]]
    assert "ทำคลิป 544 น. (รอฟิกตอบ 157 น.)" in cj.timeline_text(tl)


def _hermes_db(path, rows):
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, "
              "tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)")
    c.executemany("INSERT INTO messages (role, tool_call_id, tool_calls, timestamp) VALUES (?, ?, ?, ?)", rows)
    c.commit()
    c.close()


def test_clarify_spans_reads_hermes_asks(tmp_path):
    db = str(tmp_path / "state.db")
    ask = lambda cid, name="clarify": json.dumps([{"id": cid, "type": "function",
                                                   "function": {"name": name, "arguments": "{}"}}])
    _hermes_db(db, [("assistant", None, ask("c1"), 1000.0), ("tool", "c1", None, 1600.0),      # 10 min ask
                    ("assistant", None, ask("c2"), 2000.0), ("tool", "c2", None, 2600.0),      # outside the window
                    ("assistant", None, ask("t1", "terminal"), 1100.0), ("tool", "t1", None, 1900.0),
                    ("assistant", None, ask("c3"), 1700.0)])                                    # never answered
    assert cj.clarify_spans(900, 1800, db) == [(1000.0, 1600.0)]
    assert cj.clarify_spans(900, 1300, db) == [(1000.0, 1300.0)]                               # clipped at the end
    assert cj.clarify_spans(900, 1800, str(tmp_path / "missing.db")) == []


def test_timeline_counts_clarify_waits():
    j = job(shots=0, mode="gameplay")
    j["created"], j["events"] = "2026-11-12T02:00:00+07:00", []
    j.pop("started", None)
    for hhmm, msg in [("02:00", "created"), ("03:00", "delivered")]:
        _ev(j, hhmm, msg)
    t0 = cj._epoch(j["created"])
    tl = cj.timeline(j, asks=[(t0 + 600, t0 + 1200), (t0 + 900, t0 + 1500)])   # overlapping asks = one wait
    assert tl["wait_fix_min"] == 15


# ---------------------------------------------------------------- Omni 1.2 Flash: per-shot seconds and cost
def test_shot_seconds_default_and_per_shot():
    assert [s["seconds"] for s in job(2)["shots"]] == [10, 10]
    j = cj.new_job("t-2", "product", "Thing", "", 3, ["/tmp/r.jpg"], seconds="8,6,8")
    assert [s["seconds"] for s in j["shots"]] == [8, 6, 8]
    assert [s["seconds"] for s in cj.new_job("t-3", "hands", "T", "", 2, ["/tmp/r.jpg"], seconds="8")["shots"]] == [8, 8]


def test_shot_seconds_refuses_the_double_rate_band_and_bad_counts():
    for bad in ("12", "8,15", "2", "8,6", "x"):
        with pytest.raises(cj.Refused):
            cj.new_job("t-2", "product", "Thing", "", 3, ["/tmp/r.jpg"], seconds=bad)


def test_cost_is_per_second_and_names_the_model():
    c = cj.cost([8, 6])
    assert c["model"] == "Omni 1.2 Flash" and c["credits"] == [24, 18] and c["total"] == 42 and c["regen_one"] == 24
    assert cj.cost([10], "360p")["total"] == 10
    with pytest.raises(cj.Refused):
        cj.cost([8], "1080p")
    assert cj.parse_seconds("8,6", 0) == [8, 6]
    with pytest.raises(cj.Refused):
        cj.parse_seconds("12", 0)


def test_old_job_without_seconds_reads_as_ten():
    assert cj.shot_seconds({"k": 1}) == 10


def test_pack_sends_the_character_portrait_for_an_account_without_it(tmp_path, monkeypatch):
    chars = tmp_path / "chars"; chars.mkdir(); (chars / "น้องมุก.jpg").write_bytes(b"x")
    monkeypatch.setattr(cj, "CHAR_DIR", str(chars))
    calls = []
    monkeypatch.setattr(cj, "tg", lambda m, d, files=None: calls.append((m, d, files)) or {"message_id": 1})
    j = job(1, prod="prompt"); j["workdir"] = str(tmp_path); (tmp_path / "shot1.txt").write_text("p", encoding="utf-8")
    cj.cmd_pack(j, None, False)
    head = calls[0][1]["text"]
    assert "Omni 1.2 Flash" in head and "Ingredient แทน" in head
    assert any(f and f.get("photo", "").endswith("น้องมุก.jpg") for _, _, f in calls)
    assert "10 วิ" in calls[-2][1]["text"]
    assert calls[-1][1]["reply_markup"]["keyboard"][0][0]["text"] == "🤖 ไอยูกด Flow แทน · t-1"
    monkeypatch.setattr(cj, "CHAR_DIR", str(tmp_path / "none")); calls.clear()
    j2 = job(1, prod="prompt"); j2["workdir"] = str(tmp_path)
    cj.cmd_pack(j2, None, False)
    assert "Ingredient แทน" not in calls[0][1]["text"] and len([c for c in calls if c[0] == "sendPhoto"]) == 1


def test_cli_ingest_sends_the_next_shots_start_frame(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=2, prod="prompt"); j["workdir"] = str(tmp_path / "w")
    for s in j["shots"]:
        s["state"] = "packed"
    cj.save(j)
    src = tmp_path / "in.mp4"; src.write_bytes(b"x")
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload, files)) or {"message_id": 1})
    monkeypatch.setattr(cj, "last_frame", lambda video, out: open(out, "wb").close() or out)
    assert cj.main(["ingest", "t-1", str(src), "--shot", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["start_frame_sent"] == 2
    (method, payload, files), = sent
    assert method == "sendPhoto" and "ช็อต 2" in payload["caption"] and files["photo"].endswith("shot1_last.jpg")
    assert cj.main(["ingest", "t-1", str(src), "--shot", "2"]) == 0      # last shot: nothing follows it
    assert json.loads(capsys.readouterr().out)["start_frame_sent"] is None and len(sent) == 1


def test_start_frame_is_not_sent_for_a_shot_that_already_has_a_file(tmp_path):
    j = job(shots=2, prod="prompt"); j["workdir"] = str(tmp_path)
    cj.shot(j, 2)["state"] = "in_review"
    assert cj.next_start_frame(j, 1, "/tmp/none.mp4") is None


def test_kept_finals_older_than_a_week_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "FINALS_DIR", str(tmp_path / "finals"))
    final = tmp_path / "f.mp4"; final.write_bytes(b"a"); cover = tmp_path / "c.jpg"; cover.write_bytes(b"c")
    old = cj.keep_final("old-job", str(final), str(cover))
    cj.keep_final("new-job", str(final), str(cover), t=cj.now() + 6 * 86400)
    assert all(os.path.exists(p) for p in old)
    cj.keep_final("newer-job", str(final), str(cover), t=cj.now() + 8 * 86400)
    assert not any(os.path.exists(p) for p in old)
    assert sorted(os.listdir(tmp_path / "finals")) == ["newer-job.mp4", "newer-job_cover.jpg"]


def test_wait_on_fix_counts_overlapping_reviews_once():
    j = job(shots=2, prod="auto")
    t0 = cj._epoch(j["created"])
    j["events"] = [{"ts": cj.iso(t0), "msg": "created"},
                   {"ts": cj.iso(t0 + 600), "msg": "ready shot 1 pass=True"},
                   {"ts": cj.iso(t0 + 1200), "msg": "ready shot 2 pass=True"},
                   {"ts": cj.iso(t0 + 2400), "msg": "decide shot 2: approve"},
                   {"ts": cj.iso(t0 + 2400), "msg": "decide shot 1: approve"}]
    assert cj.timeline(j, t0 + 3000)["wait_fix_min"] == 30          # 600 → 2400, not 30 + 20


# ---------------------------------------------------------------- close (🏁 button / 5 min timer)
@pytest.fixture
def closing(tmp_path, monkeypatch):
    """A delivered 🎬 job with a workdir under WORK and one Downloads dir; Telegram calls recorded."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path / "jobs")); monkeypatch.setenv("CLIPJOB_NO_TIMER", "1")
    monkeypatch.delenv("CLIPJOB_NO_TG", raising=False)
    monkeypatch.setattr(cj, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(cj, "FINALS_DIR", str(tmp_path / "finals"))
    monkeypatch.setattr(cj, "CLIP_LOG", str(tmp_path / "logs" / "clip-log.jsonl"))
    dl = tmp_path / "dl"; dl.mkdir(); monkeypatch.setattr(cj, "DOWNLOADS", [str(dl)])
    sent = []
    monkeypatch.setattr(cj, "tg", lambda m, p=None, files=None: sent.append((m, p)) or {"message_id": 1})
    monkeypatch.setattr(cj, "av_durations", lambda p: (20.0, 20.0))
    monkeypatch.setattr(cj, "run", lambda cmd: (0, json.dumps({"ok": True}), ""))
    wd = tmp_path / "work" / "g-1"
    assert cj.main(["new", "g-1", "--mode", "gameplay", "--product", "Game", "--link", "https://s.shopee.co.th/x",
                    "--workdir", str(wd)]) == 0
    final = wd / "final.mp4"; final.write_bytes(b"FINAL"); cover = wd / "thumb.jpg"; cover.write_bytes(b"COVER")
    args = ["deliver", "g-1", "--final", str(final), "--hashtags", "#game", "--cover", str(cover), "--caption", "c",
            "--hook-id", "gph-1", "--category", "game", "--post-hook", "ใครเล่นเกมนี้จบแล้วต้องลองโหมดใหม่"]
    sent.clear()
    assert cj.main(args) == 0
    return {"wd": wd, "dl": dl, "sent": sent, "args": args, "final": final}


def test_deliver_shows_the_close_button_and_arms_the_timer(closing):
    last = [p for m, p in closing["sent"] if m == "sendMessage"][-1]
    assert last["reply_markup"]["keyboard"] == [[{"text": "🏁 จบงาน · g-1"}]]
    c = cj.load("g-1")["close"]
    assert c["state"] == "pending" and c["token"] and c["due_ts"] > cj.now() + cj.CLOSE_S - 5
    assert cj.parse_close_text("🏁 จบงาน · g-1") == "g-1" and cj.parse_close_text("จบงาน") is None


def test_close_deletes_only_provable_junk(closing):
    wd, dl = closing["wd"], closing["dl"]
    for f in ("frame_sheet.jpg", "shot1.v.jpg", "shot1_last.jpg", "chrome.log", "plan.json", "subs.ass", "src_1.mp4"):
        (wd / f).write_bytes(f.encode())
    (wd / "fonts").mkdir(); (wd / "fonts" / "x_sheet.png").write_bytes(b"font")
    (dl / "final_copy.mp4").write_bytes(b"FINAL")          # the delivered final, downloaded
    (dl / "Flow_take_1.mp4").write_bytes(b"src_1.mp4")      # byte twin of a workdir source
    (dl / "other.mp4").write_bytes(b"someone else's")
    j = cj.load("g-1"); j["shots"] = [{"k": 1, "state": "approved", "file": str(dl / "Flow_take_1.mp4")}]; cj.save(j)
    assert cj.main(["decide", "--text", "🏁 จบงาน · g-1"]) == 0
    left = sorted(p.name for p in wd.iterdir())
    assert left == ["fonts", "plan.json", "src_1.mp4", "subs.ass", "thumb.jpg"]   # the final lives on in finals/
    assert (wd / "fonts" / "x_sheet.png").exists() and wd.is_dir()
    assert sorted(p.name for p in dl.iterdir()) == ["other.mp4"]
    j = cj.load("g-1")
    assert j["shots"][0]["file"] == str(wd / "src_1.mp4")                   # a revision still finds the shot
    assert j["close"]["state"] == "closed" and j["close"]["by"] == "tap" and j["status"] == "delivered"
    assert all(os.path.exists(k) for k in j["delivery"]["kept"])
    msg = closing["sent"][-1][1]
    assert "ปิดงาน g-1" in msg["text"] and msg["reply_markup"] == {"remove_keyboard": True}


def test_tap_then_timer_and_timer_then_tap(closing, capsys):
    tok = cj.load("g-1")["close"]["token"]
    assert cj.main(["close", "g-1", "--auto", "--token", tok, "--after", "0"]) == 0
    assert cj.load("g-1")["close"]["by"] == "auto"
    assert "อัตโนมัติ" in closing["sent"][-1][1]["text"]
    assert cj.main(["decide", "--text", "🏁 จบงาน · g-1"]) == 0                # late tap
    assert closing["sent"][-1][1]["text"] == "งาน g-1 ปิดไปแล้วค่ะ"
    assert cj.load("g-1")["close"]["by"] == "auto"
    n = len(closing["sent"])
    assert cj.main(["close", "g-1", "--auto", "--token", tok, "--after", "0"]) == 0   # a second timer: no-op
    assert len(closing["sent"]) == n and "skipped" in capsys.readouterr().out


def test_reopen_voids_the_timer_and_redeliver_arms_a_new_one(closing, capsys):
    old = cj.load("g-1")["close"]["token"]
    assert cj.main(["reopen", "g-1", "--reason", "ฟิก: แก้ซับ"]) == 0
    assert "close" not in cj.load("g-1")
    assert cj.main(["close", "g-1", "--auto", "--token", old, "--after", "0"]) == 0
    assert "close" not in cj.load("g-1")
    closing["final"].write_bytes(b"FINAL v2")
    assert cj.main(closing["args"]) == 0
    new = cj.load("g-1")["close"]["token"]
    assert new != old
    assert cj.main(["close", "g-1", "--auto", "--token", old, "--after", "0"]) == 0
    assert cj.load("g-1")["close"]["state"] == "pending"
    assert cj.main(["close", "g-1", "--auto", "--token", new, "--after", "0"]) == 0
    assert cj.load("g-1")["close"]["state"] == "closed"


def test_overdue_close_is_swept_by_the_next_command(closing):
    j = cj.load("g-1"); j["close"]["due_ts"] = cj.now() - cj.CLOSE_GRACE_S - 1; cj.save(j)
    assert cj.main(["status"]) == 0
    c = cj.load("g-1")["close"]
    assert c["state"] == "closed" and c["by"] == "auto (late)"


def test_close_without_job_closes_every_waiting_one(closing):
    assert cj.main(["close"]) == 0
    assert cj.load("g-1")["close"]["by"] == "manual"


def test_close_refuses_an_open_job_and_skips_a_workdir_outside_work(closing, tmp_path, monkeypatch):
    assert cj.main(["new", "o-1", "--mode", "gameplay", "--product", "G", "--workdir", str(tmp_path / "w2")]) == 0
    assert cj.main(["close", "o-1"]) == 1
    monkeypatch.setattr(cj, "WORK", str(tmp_path / "elsewhere"))
    (closing["wd"] / "a_sheet.jpg").write_bytes(b"x")
    assert cj.main(["close", "g-1"]) == 0
    assert (closing["wd"] / "a_sheet.jpg").exists()


def test_close_then_reopen_then_redeliver(closing):
    assert cj.main(["decide", "--text", "🏁 จบงาน · g-1"]) == 0
    assert not closing["final"].exists()                                   # the kept copy is in finals/
    assert cj.main(["reopen", "g-1", "--reason", "ฟิก: แก้ซับ"]) == 0
    closing["final"].write_bytes(b"FINAL v2")                             # the rebuilt final, same cover
    assert cj.main(closing["args"]) == 0
    j = cj.load("g-1")
    assert j["status"] == "delivered" and j["close"]["state"] == "pending" and j["timing"]


# ---------------------------------------------------------------- Secretary copy (Fix 2026-11-17)
@pytest.fixture
def mirroring(tmp_path, monkeypatch):
    """Deliver a 🎬 job with the Secretary env set; `run` calls recorded, mirror sent inline."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path / "jobs")); monkeypatch.setenv("CLIPJOB_NO_TIMER", "1")
    monkeypatch.delenv("CLIPJOB_NO_TG", raising=False)
    monkeypatch.setenv("CLIPJOB_MIRROR_INLINE", "1")
    monkeypatch.setenv(cj.MIRROR_TOKEN_ENV, "123:SECRET-TOKEN-VALUE")
    monkeypatch.setenv(cj.MIRROR_CHAT_ENV, "555")
    monkeypatch.setattr(cj, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(cj, "FINALS_DIR", str(tmp_path / "finals"))
    monkeypatch.setattr(cj, "CLIP_LOG", str(tmp_path / "logs" / "clip-log.jsonl"))
    monkeypatch.setattr(cj, "DOWNLOADS", [])
    sent = []
    monkeypatch.setattr(cj, "tg", lambda m, p=None, files=None: sent.append((m, p)) or {"message_id": 1})
    monkeypatch.setattr(cj, "av_durations", lambda p: (20.0, 20.0))
    calls, fail = [], set()

    def fake_run(cmd):
        calls.append(cmd)
        mirror = cmd[0] == "env"
        script = os.path.basename(next(c for c in cmd if c.endswith(".py")))
        if mirror and script in fail:
            return 1, json.dumps({"ok": False}), "boom"
        return 0, json.dumps({"ok": True}), ""
    monkeypatch.setattr(cj, "run", fake_run)
    wd = tmp_path / "work" / "g-1"
    assert cj.main(["new", "g-1", "--mode", "gameplay", "--product", "Game", "--link", "https://s.shopee.co.th/x",
                    "--workdir", str(wd)]) == 0
    final = wd / "final.mp4"; final.write_bytes(b"FINAL"); cover = wd / "thumb.jpg"; cover.write_bytes(b"COVER")
    args = ["deliver", "g-1", "--final", str(final), "--hashtags", "#game", "--cover", str(cover), "--caption", "cap",
            "--hook-id", "gph-1", "--category", "game", "--post-hook", "ใครเล่นเกมนี้จบแล้วต้องลองโหมดใหม่"]
    return {"args": args, "calls": calls, "fail": fail, "sent": sent, "monkeypatch": monkeypatch}


def _mirror_calls(calls):
    return [c for c in calls if c[0] == "env"]


def test_secretary_copy_sends_clip_and_buttons_as_the_secretary_bot(mirroring):
    assert cj.main(mirroring["args"]) == 0
    mc = _mirror_calls(mirroring["calls"])
    assert [os.path.basename(c[3]) for c in mc] == ["send_clip.py", "send_copy_buttons.py", "send_photo.py"]
    assert mc[2][4].endswith("finals/g-1_cover.jpg")            # the kept cover
    assert all(c[1] == f"TG_TOKEN_ENV={cj.MIRROR_TOKEN_ENV}" and "555" in c for c in mc)
    assert mc[0][4].endswith("finals/g-1.mp4")                  # the kept copy, which cleanup never deletes
    assert mc[1][4:6] == ["#game", "https://s.shopee.co.th/x"]
    assert mc[1][-1] == "ใครเล่นเกมนี้จบแล้วต้องลองโหมดใหม่"            # the 🪝 button
    assert not any("SECRET-TOKEN-VALUE" in x for c in mirroring["calls"] for x in c)   # token never on argv
    j = cj.load("g-1")
    assert j["status"] == "delivered" and j["delivery"]["mirror"]["state"] == "ok"
    assert j["close"]["state"] == "pending"                     # the copy does not disturb the 🏁 timer


def test_secretary_copy_off_without_env(mirroring):
    mirroring["monkeypatch"].delenv(cj.MIRROR_TOKEN_ENV)
    assert cj.main(mirroring["args"]) == 0
    assert _mirror_calls(mirroring["calls"]) == []
    m = cj.load("g-1")["delivery"]["mirror"]                    # recorded anyway, so it can be sent later
    assert m["state"] == "off" and cj.MIRROR_TOKEN_ENV in m["why"]
    mirroring["monkeypatch"].setenv(cj.MIRROR_TOKEN_ENV, "123:SECRET-TOKEN-VALUE")
    assert cj.main(["mirror", "g-1"]) == 0
    assert [os.path.basename(c[3]) for c in _mirror_calls(mirroring["calls"])] == ["send_clip.py", "send_copy_buttons.py",
                                                                                   "send_photo.py"]
    assert cj.load("g-1")["delivery"]["mirror"]["state"] == "ok"


def test_scrubbed_deliver_adopts_secretary_env_from_the_gateway(mirroring, tmp_path):
    """2026-11-17 d-branner-toothpaste: deliver ran from Hermes' execute_code (secret-looking names scrubbed)."""
    mp = mirroring["monkeypatch"]
    mp.setenv(cj.MIRROR_TOKEN_ENV, ""); mp.setenv(cj.MIRROR_CHAT_ENV, "")    # restored to the test's env afterwards
    proc = tmp_path / "proc"; (proc / "425").mkdir(parents=True)
    (proc / "425" / "environ").write_bytes(b"PATH=/bin\0SECRETARY_TELEGRAM_BOT_TOKEN=9:GW-TOKEN\0"
                                           b"SECRETARY_TELEGRAM_CHAT_ID=777\0")
    pidf = tmp_path / "gateway.pid"; pidf.write_text(json.dumps({"pid": 425, "kind": "hermes-gateway"}))
    mp.setattr(cj, "PROC", str(proc)); mp.setattr(cj, "GATEWAY_PID", str(pidf))
    assert cj.main(mirroring["args"]) == 0
    mc = _mirror_calls(mirroring["calls"])
    assert [os.path.basename(c[3]) for c in mc] == ["send_clip.py", "send_copy_buttons.py", "send_photo.py"]
    assert all("777" in c for c in mc)
    assert not any("GW-TOKEN" in x for c in mirroring["calls"] for x in c)   # token never on argv
    assert os.environ[cj.MIRROR_TOKEN_ENV] == "9:GW-TOKEN"                  # children inherit it
    assert cj.load("g-1")["delivery"]["mirror"]["state"] == "ok"


def test_adopt_gateway_env_keeps_set_names_and_survives_a_missing_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv(cj.MIRROR_TOKEN_ENV, "mine"); monkeypatch.setenv(cj.MIRROR_CHAT_ENV, "1")
    monkeypatch.setenv("TZ", "Asia/Bangkok")
    assert cj.adopt_gateway_env() == []                                     # nothing missing: no read at all
    monkeypatch.setenv(cj.MIRROR_CHAT_ENV, "")
    monkeypatch.setattr(cj, "GATEWAY_PID", str(tmp_path / "absent.pid"))
    assert cj.adopt_gateway_env() == [] and os.environ[cj.MIRROR_TOKEN_ENV] == "mine"


def test_secretary_copy_failure_never_blocks_delivery_and_mirror_resends(mirroring, capsys):
    mirroring["fail"].add("send_clip.py")
    assert cj.main(mirroring["args"]) == 0                      # Fix's delivery still succeeded
    j = cj.load("g-1")
    assert j["status"] == "delivered" and j["delivery"]["mirror"]["state"] == "failed"
    assert [os.path.basename(c[3]) for c in _mirror_calls(mirroring["calls"])] == ["send_clip.py"]  # no buttons
    mirroring["calls"].clear(); mirroring["fail"].clear()
    assert cj.main(["mirror", "g-1"]) == 0
    assert [os.path.basename(c[3]) for c in _mirror_calls(mirroring["calls"])] == ["send_clip.py", "send_copy_buttons.py",
                                                                                   "send_photo.py"]
    assert cj.load("g-1")["delivery"]["mirror"]["state"] == "ok"
    mirroring["calls"].clear()
    assert cj.main(["mirror", "g-1"]) == 0                      # already sent: nothing re-posted
    assert _mirror_calls(mirroring["calls"]) == []


def test_secretary_copy_rerun_skips_the_clip_already_sent(mirroring):
    mirroring["fail"].add("send_copy_buttons.py")
    assert cj.main(mirroring["args"]) == 0
    mirroring["calls"].clear(); mirroring["fail"].clear()
    assert cj.main(["mirror", "g-1"]) == 0
    assert [os.path.basename(c[3]) for c in _mirror_calls(mirroring["calls"])] == ["send_copy_buttons.py", "send_photo.py"]


def test_secretary_copy_auto_failure_tells_fix_and_keeps_the_close_button(mirroring):
    mirroring["fail"].add("send_clip.py")
    assert cj.main(mirroring["args"]) == 0
    mirroring["sent"].clear()
    assert cj.main(["mirror", "g-1", "--auto"]) == 1
    msg = [p for m, p in mirroring["sent"] if m == "sendMessage"][-1]
    assert "Secretary" in msg["text"] and "clipjob.py mirror g-1" in msg["text"]
    assert msg["reply_markup"]["keyboard"] == [[{"text": "🏁 จบงาน · g-1"}]]


def test_send_clip_reads_a_named_token_and_tags_ledger(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("send_clip_t", os.path.join(os.path.dirname(cj.__file__), "send_clip.py"))
    sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
    monkeypatch.setenv("TG_TOKEN_ENV", "OTHER_BOT"); monkeypatch.setenv("OTHER_BOT", "9:abc")
    assert sc.read_token() == "9:abc"
    monkeypatch.setenv("OTHER_BOT", "")
    with pytest.raises(SystemExit):
        sc.read_token()


def test_check_delivery_ignores_copies_sent_as_another_bot(tmp_path):
    led = tmp_path / "d.jsonl"; clog = tmp_path / "c.jsonl"
    led.write_text(json.dumps({"ts": "2026-11-17T10:00:00", "file": "f.mp4", "ok": True, "message_id": 1,
                               "size": 1, "remote_size": 1, "attempt": 1}) + "\n" +
                   json.dumps({"ts": "2026-11-17T10:01:00", "file": "f.mp4", "ok": False, "attempt": 2,
                               "via": "SECRETARY_TELEGRAM_BOT_TOKEN", "reason": "boom"}) + "\n")
    clog.write_text("")
    env = dict(os.environ, CLIP_LEDGER=str(led), CLIP_LOG=str(clog))
    p = subprocess.run([sys.executable, os.path.join(os.path.dirname(cj.__file__), "check_delivery.py")],
                       env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


# ---------------------------------------------------------------- 2026-11-19 tunes
def test_ready_needs_an_identity_verdict_of_this_file(tmp_path, monkeypatch, capsys):
    """aukey-pby92 2026-11-18: the 3-frame check passed a powerbank that morphed mid-shot; the ref comparison
    ran after the review had gone to Fix."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=1, mode="product", prod="auto"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "auto"})
    cj.save(j)
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    ready = ["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--no-send"]
    assert cj.main(ready + ["--identity", "match"]) == 1
    assert "idcheck" in capsys.readouterr().err
    made = {}
    monkeypatch.setattr(cj, "id_sheet", lambda raw, refs, out, dur: (made.update(refs=refs, dur=dur) or out,
                                                                      [0.5, 2.5, 4.5, 6.5, 8.5, 9.9]))
    assert cj.main(["idcheck", "t-1", "1", "--raw", str(raw)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert made == {"refs": ["/tmp/ref.jpg"], "dur": 10.0}
    assert "tile 1 = REFERENCE" in res["ask_vision"] and "tile 7 = shot at 9.9 s" in res["ask_vision"]
    assert cj.main(ready) == 1                                   # no verdict
    assert "--identity" in capsys.readouterr().err
    assert cj.main(ready + ["--identity", "drift:"]) == 1         # a drift needs the part
    assert cj.main(ready + ["--identity", "drift:display bigger at 2-4 s, colour white at 5 s"]) == 0
    g = cj.load("t-1")["shots"][0]["gates"]["identity"]
    assert g["ok"] is False and "display bigger" in g["note"]


CHANGE = {"verdict": "change", "sheet": "/w/shot1_prod.jpg",
          "refs": {"ref1.jpg": {"matched": 20, "of": 20, "baseline_t": 0.0, "peak": 36.0,
                                "flags": [{"band": "bottom", "from": 3.0, "to": 5.5, "de": 37.6}]}}}


def test_pixel_change_blocks_a_match_verdict_until_answered(tmp_path, monkeypatch, capsys):
    """cal-d-protein-1mo 2026-11-25: the boxes' navy bottom band went brown/pink at 3 s; the vision read said MATCH."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=1, mode="product", prod="auto"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "auto"})
    cj.save(j)
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    monkeypatch.setattr(cj, "id_sheet", lambda raw, refs, out, dur: (out, [0.5, 2.5, 4.5, 6.5, 8.5, 9.9]))
    monkeypatch.setattr(cj, "prod_check", lambda raw, refs, out: CHANGE)
    assert cj.main(["idcheck", "t-1", "1", "--raw", str(raw)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["pixel"]["verdict"] == "change" and "bottom" in res["ask_vision"] and "3.0" in res["ask_vision"]
    ready = ["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--no-send"]
    assert cj.main(ready + ["--identity", "match"]) == 1
    assert "pixel" in capsys.readouterr().err
    assert cj.main(ready + ["--identity", "match", "--pixel-ok", "hand covers the band 3-5 s, colour same after"]) == 0
    g = cj.load("t-1")["shots"][0]["gates"]
    assert g["identity"]["ok"] and "hand covers" in g["pixel"]["note"]


def test_pixel_change_with_a_drift_verdict_needs_no_answer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=1, mode="product", prod="auto"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "auto"})
    cj.save(j)
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    monkeypatch.setattr(cj, "id_sheet", lambda raw, refs, out, dur: (out, [0.5, 2.5, 4.5, 6.5, 8.5, 9.9]))
    monkeypatch.setattr(cj, "prod_check", lambda raw, refs, out: CHANGE)
    assert cj.main(["idcheck", "t-1", "1", "--raw", str(raw)]) == 0
    capsys.readouterr()
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--no-send",
                    "--identity", "drift:bottom band brown from 3 s"]) == 0
    assert cj.load("t-1")["shots"][0]["gates"]["identity"]["ok"] is False


def test_prompt_reply_runs_the_pixel_check_and_tells_fix(tmp_path, monkeypatch, capsys):
    """kiiz/cal-d 2026-11-25: 📝 has no identity read at all; the pixel check costs no vision, so it still runs."""
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {})
    monkeypatch.setattr(cj, "prod_check", lambda raw, refs, out: CHANGE)
    j, dst = reviewed_shot(tmp_path, monkeypatch)
    assert cj.main(["ready", "t-1", "1", "--raw", dst]) == 0
    assert cj.shot(cj.load("t-1"), 1)["state"] == "approved"            # still his review
    assert sent and "ล่างสุด" in sent[-1][1]["text"] and "3.0" in sent[-1][1]["text"]


def test_identity_sheet_is_tied_to_the_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=1, mode="product", prod="auto"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["state"] = "submitted"; cj.shot(j, 1)["attempts"].append({"via": "auto"})
    raw = tmp_path / "s.mp4"; raw.write_bytes(b"x")
    cj.shot(j, 1)["idcheck"] = {"sig": cj.file_sig(str(raw))}; cj.save(j)
    raw.write_bytes(b"the regenerated take")
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    assert cj.main(["ready", "t-1", "1", "--raw", str(raw), "--frame", "pass", "--identity", "match", "--no-send"]) == 1


def chained(tmp_path, faces, shots=3):
    """A presenter job whose shots 1..len(faces) have files; faces[m-1] = does shot m's last frame show her."""
    j = job(shots=shots, prod="prompt"); j["workdir"] = str(tmp_path)
    for m in range(1, len(faces) + 1):
        cj.shot(j, m).update({"state": "approved", "file": str(tmp_path / f"s{m}.mp4")})
    return j


def test_start_frame_skips_a_shot_without_her_face(tmp_path, monkeypatch):
    """uneed-pb-1 2026-11-18: hands-only shot 2 -> shot 3 started on it -> a new woman, three gens."""
    monkeypatch.setattr(cj, "last_frame", lambda video, out: open(out, "wb").close() or out)
    seen = {"shot1_last.jpg": True, "shot2_last.jpg": False}
    monkeypatch.setattr(cj, "has_face", lambda img: seen[os.path.basename(img)])
    sf = cj.start_frame_for(chained(tmp_path, [True, False]), 3)
    assert sf["from"] == 1 and sf["faceless"] == [2] and sf["file"].endswith("shot1_last.jpg")
    assert "ไม่เห็นหน้า เลยใช้ท้ายช็อต 1" in cj.start_frame_text(chained(tmp_path, [True, False]), 3, sf)
    seen["shot1_last.jpg"] = False                               # no earlier face at all: no start frame
    sf = cj.start_frame_for(chained(tmp_path, [False, False]), 3)
    assert sf["file"] is None and sf["faceless"] == [2, 1]
    assert "ไม่ต้องแนบ start frame" in cj.start_frame_text(chained(tmp_path, [False, False]), 3, sf)


def test_start_frame_keeps_the_old_way_when_the_face_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "last_frame", lambda video, out: open(out, "wb").close() or out)
    monkeypatch.setattr(cj, "has_face", lambda img: None)
    sf = cj.start_frame_for(chained(tmp_path, [True, True]), 3)
    assert sf["from"] == 2 and sf["unchecked"] is True


def test_product_modes_chain_without_a_face_check(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "last_frame", lambda video, out: open(out, "wb").close() or out)

    def boom(img):
        raise AssertionError("📦/✋ shots have no face to look for")
    monkeypatch.setattr(cj, "has_face", boom)
    j = job(shots=2, mode="product", prod="prompt"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1).update({"state": "approved", "file": str(tmp_path / "s1.mp4")})
    assert cj.start_frame_for(j, 2)["from"] == 1


def test_cli_ingest_tells_fix_not_to_attach_a_faceless_start_frame(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=2, prod="prompt"); j["workdir"] = str(tmp_path / "w")
    for s in j["shots"]:
        s["state"] = "packed"
    cj.save(j)
    src = tmp_path / "in.mp4"; src.write_bytes(b"x")
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {"message_id": 1})
    monkeypatch.setattr(cj, "last_frame", lambda video, out: open(out, "wb").close() or out)
    monkeypatch.setattr(cj, "has_face", lambda img: False)
    assert cj.main(["ingest", "t-1", str(src), "--shot", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["start_frame_sent"] is None and out["start_frame"]["faceless"] == [1]
    (method, payload), = sent
    assert method == "sendMessage" and "ไม่ต้องแนบ start frame" in payload["text"] and "น้องมุก" in payload["text"]


def test_intake_job_is_listed_then_promoted_by_new(tmp_path, monkeypatch, capsys):
    """nual-loop-240w 2026-11-18: a content_filter refusal wiped Hermes' history and `status` showed no job."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setattr(cj, "WORK", str(tmp_path / "work"))
    (tmp_path / "chars").mkdir(); (tmp_path / "chars" / "น้องมิลค์.jpg").write_bytes(b"p")
    monkeypatch.setattr(cj, "CHAR_DIR", str(tmp_path / "chars"))
    assert cj.main(["intake", "n-1", "--product", "Cable", "--link", "https://s.shopee.co.th/x"]) == 0
    assert cj.main(["intake", "n-1", "--product", "Cable"]) == 1            # one record per slug
    assert cj.main(["note", "n-1", "board sent (msg 12208); next: wait for approval + Q3"]) == 0
    capsys.readouterr()
    assert cj.main(["status"]) == 0
    row, = json.loads(capsys.readouterr().out)["open_jobs"]
    assert row["stage"] == "intake" and "board sent" in row["last"][-1]
    assert cj.main(["pack", "n-1", "--no-send"]) == 1                       # nothing runs before `new`
    assert "still at intake" in capsys.readouterr().err
    ref = tmp_path / "ref1.jpg"; ref.write_bytes(b"r")
    assert cj.main(["board", "n-1", "--hook-id", "custom-cable-1"]) == 0
    created = cj.load("n-1")["created"]
    assert cj.main(["new", "n-1", "--mode", "presenter", "--product", "Cable", "--link", "https://s.shopee.co.th/x",
                    "--shots", "2", "--ref", str(ref), "--character", "น้องมิลค์"]) == 0
    j = cj.load("n-1")
    assert "stage" not in j and len(j["shots"]) == 2 and j["created"] == created
    assert [e["msg"] for e in j["events"]][:3] == ["intake", "note: board sent (msg 12208); next: wait for approval + Q3",
                                                   "board sent (hook custom-cable-1)"]
    assert cj.main(["new", "n-1", "--mode", "presenter", "--product", "Cable", "--shots", "2", "--ref", str(ref),
                    "--character", "น้องมิลค์"]) == 1                     # a real job is never overwritten


# ---------------------------------------------------------------- 2026-11-22 tunes
def reviewed_shot(tmp_path, monkeypatch, mode="product", shots=2):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=shots, mode=mode, prod="prompt"); j["workdir"] = str(tmp_path)
    for s in j["shots"]:
        s["state"] = "packed"
    raw = tmp_path / "in.mp4"; raw.write_bytes(b"x")
    dst = cj.ingest(j, 1, str(raw)); open(dst, "wb").write(b"x"); cj.save(j)
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 10.0, "kbps": 3000, "has_audio": True})
    return j, dst


def test_prompt_reply_is_fix_review_and_approves_at_once(tmp_path, monkeypatch, capsys):
    """Fix 2026-11-22: "gen prompt แล้วผม reply กลับ ถือว่ารีวิวแล้ว ตีผ่านหมด ไม่ต้องให้ผม confirm"."""
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {})
    monkeypatch.setattr(cj, "id_sheet", lambda *a: (_ for _ in ()).throw(AssertionError("no idcheck in 📝")))
    j, dst = reviewed_shot(tmp_path, monkeypatch)
    assert cj.main(["ready", "t-1", "1", "--raw", dst]) == 0      # no --frame, no --identity, no idcheck
    res = json.loads(capsys.readouterr().out)
    assert res["auto_approved"] and "shot 2" in res["next"]
    j = cj.load("t-1")
    assert cj.shot(j, 1)["state"] == "approved" and cj.shot(j, 1)["gates"]["frame"]["note"] == cj.FIX_REVIEWED
    assert not any((p or {}).get("reply_markup", {}).get("keyboard") for _, p in sent)   # no ✅/🔁 buttons
    assert not sent                                               # clean shot: nothing to tell Fix


def test_prompt_reply_with_a_gate_note_informs_without_buttons(tmp_path, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {})
    j, dst = reviewed_shot(tmp_path, monkeypatch)
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 480, "h": 854, "dur": 10.0, "kbps": 900, "has_audio": True})
    assert cj.main(["ready", "t-1", "1", "--raw", dst]) == 0
    assert cj.shot(cj.load("t-1"), 1)["state"] == "approved"
    (method, payload), = sent
    assert "ผ่านอัตโนมัติ" in payload["text"] and "720x1280" in payload["text"]
    # no ✅/🔁 (his file is his review); shot 2 still waits, so the 🤖 takeover button stays on screen
    assert payload["reply_markup"]["keyboard"] == [[{"text": "🤖 ไอยูกด Flow แทน · t-1"}]]


# ---------------------------------------------------------------- 🤖 takeover (Fix 2026-11-23)
def test_pack_offers_the_takeover_button_with_start_shot_and_cost(tmp_path, monkeypatch):
    """Fix 2026-11-23: a 📝 pack carries a button that hands Flow back to Hermes."""
    calls = []
    monkeypatch.setattr(cj, "tg", lambda m, d, files=None: calls.append((m, d)) or {"message_id": 1})
    j = cj.new_job("t-1", "presenter", "Thing", "https://s.shopee.co.th/x", 2, ["/tmp/ref.jpg"],
                   character="น้องมุก", seconds="8,6")
    cj.set_production(j, "prompt"); j["workdir"] = str(tmp_path)
    for k in (1, 2):
        (tmp_path / f"shot{k}.txt").write_text("p", encoding="utf-8")
    cj.cmd_pack(j, None, False)
    m, d = calls[-1]
    assert d["reply_markup"]["keyboard"] == [[{"text": "🤖 ไอยูกด Flow แทน · t-1"}]]
    assert "เริ่มที่ช็อต 1" in d["text"] and "≈42 เครดิต" in d["text"]       # 8 s + 6 s at 3 cr/s
    assert "ทำต่อ" not in d["reply_markup"]["keyboard"][0][0]["text"]       # pending-work-triage's word


def test_no_takeover_button_after_a_fallback(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cj, "tg", lambda m, d, files=None: calls.append((m, d)) or {"message_id": 1})
    j = job(1, prod="auto"); j["workdir"] = str(tmp_path); (tmp_path / "shot1.txt").write_text("p", encoding="utf-8")
    cj.fallback(j, "unusual activity")
    cj.cmd_pack(j, None, False)
    assert not any((d or {}).get("reply_markup", {}).get("keyboard") for _, d in calls)
    assert "why" in cj.takeover(j) and j["production"] == "prompt"


def test_takeover_tap_unpacks_and_reserve_accepts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {})
    j = job(shots=2, prod="prompt")
    for s in j["shots"]:
        s["state"] = "packed"
    cj.save(j)
    assert cj.main(["decide", "--text", "🤖 ไอยูกด Flow แทน · t-1"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["takeover"] and res["todo"] == [1, 2] and "flow-driver" in res["next"]
    j = cj.load("t-1")
    assert j["production"] == "auto" and [s["state"] for s in j["shots"]] == ["pending", "pending"]
    assert "ไอยูกด Flow ต่อเอง" in sent[-1][1]["text"]
    cj.reserve(j, 1, None, 1000)                                             # the switch is real
    # a second tap is harmless
    cj.save(j); sent.clear()
    assert cj.main(["decide", "--text", "🤖 ไอยูกด Flow แทน · t-1"]) == 0
    assert json.loads(capsys.readouterr().out)["takeover"] is False and "อยู่แล้ว" in sent[-1][1]["text"]


def test_takeover_keeps_a_file_fix_already_sent_as_his_review(tmp_path, monkeypatch, capsys):
    """Shot 1's file arrived (ingested, not readied yet), then the 🤖 tap: shot 1 is still Fix-reviewed."""
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {})
    j, dst = reviewed_shot(tmp_path, monkeypatch)
    assert cj.main(["decide", "--text", "🤖 ไอยูกด Flow แทน · t-1"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["todo"] == [2] and "ready t-1 K" in res["next"] and "shot 1" in res["next"]
    assert cj.main(["ready", "t-1", "1", "--raw", dst]) == 0
    assert cj.shot(cj.load("t-1"), 1)["state"] == "approved"                  # no vision review asked


def test_takeover_on_a_closed_job_only_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    sent = []
    monkeypatch.setattr(cj, "tg", lambda method, payload=None, files=None: sent.append((method, payload)) or {})
    j = job(shots=1, prod="prompt"); j["status"] = "cancelled"; cj.save(j)
    assert cj.main(["decide", "--text", "🤖 ไอยูกด Flow แทน · t-1"]) == 0
    assert "ปิดไปแล้ว" in sent[-1][1]["text"] and cj.load("t-1")["production"] == "prompt"


def test_fix_can_replace_an_approved_prompt_shot(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "tg", lambda *a, **k: {})
    j, dst = reviewed_shot(tmp_path, monkeypatch)
    assert cj.main(["ready", "t-1", "1", "--raw", dst]) == 0
    j = cj.load("t-1")
    dst2 = cj.ingest(j, 1, str(tmp_path / "in.mp4"))
    assert dst2.endswith("shot1_a2.mp4") and cj.shot(j, 1)["state"] == "submitted"
    auto = job(shots=1, prod="auto"); render(auto, 1, 1000); cj.decide(auto, 1, "approve")
    with pytest.raises(cj.Refused):
        cj.ingest(auto, 1, "/tmp/x.mp4")                          # 🤖: a regen goes through 🔁


def test_prompt_shots_log_estimated_credits(tmp_path, monkeypatch):
    """six 📝 jobs of 11-19..22 logged credits: null."""
    j, _ = reviewed_shot(tmp_path, monkeypatch)
    assert cj.billed_credits(j) == [30]
    a = job(shots=1, prod="auto"); a["shots"][0]["seconds"] = 6
    cj.reserve(a, 1, None, 1000); cj.submitted(a, 1)
    assert cj.billed_credits(a) == [18] and a["shots"][0]["attempts"][-1]["credits_est"]


def test_identity_kinds_word_the_review_and_count_puts_regen_first():
    """eucerin 2026-11-19 read "สินค้าเพี้ยน" for a wrong presenter; onesuper 2026-11-22 shipped 2 compartments vs 3."""
    assert cj.parse_identity("presenter:ponytail, pink blouse")["note"].startswith("หน้าคนไม่ตรงตัวละคร")
    c = cj.parse_identity("count:2 compartments vs 3")
    assert c["kind"] == "count" and c["note"].startswith("จำนวนชิ้น")
    assert cj.parse_identity("drift:body thicker")["note"].startswith("สินค้าไม่ตรง")
    with pytest.raises(cj.Refused):
        cj.parse_identity("count:")
    row = cj.review_keyboard("t-1", 1, regen_first=True)["keyboard"][0]
    assert [b["text"] for b in row] == ["🔁 gen ใหม่ ช็อต 1 · t-1", "✅ ผ่าน ช็อต 1 · t-1"]


def test_a_thai_name_outside_the_voiceover_is_refused(tmp_path):
    """champion-trashbag-roll 2026-11-22: Flow painted 'น้องเอิร์ธ' on the wall."""
    j = job(shots=1, prod="prompt"); j["workdir"] = str(tmp_path)
    (tmp_path / "shot1.txt").write_text('The presenter is น้องมุก (attached chip).\n'
                                        'Audio (Thai voiceover): "สวัสดีค่ะ ลิงก์อยู่ใต้คลิปนะ"', encoding="utf-8")
    with pytest.raises(cj.Refused, match="น้องมุก"):
        cj.name_check(j, 1)
    (tmp_path / "shot1.txt").write_text('The presenter (the attached character chip).\n'
                                        'Audio (Thai voiceover): "น้องแมวชอบมาก ลิงก์อยู่ใต้คลิปนะ"', encoding="utf-8")
    cj.name_check(j, 1)                                          # a name inside the quoted line is spoken, fine


def test_presenter_needs_a_portrait(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setattr(cj, "CHAR_DIR", str(tmp_path / "chars"))
    ref = tmp_path / "r.jpg"; ref.write_bytes(b"r")
    args = ["new", "p-1", "--mode", "presenter", "--product", "x", "--shots", "1", "--ref", str(ref),
            "--character", "น้องเอิร์ธ", "--workdir", str(tmp_path / "w")]
    assert cj.main(["intake", "p-1", "--product", "x", "--workdir", str(tmp_path / "w")]) == 0
    assert cj.main(["board", "p-1", "--hook-id", "gadget-1"]) == 0
    assert cj.main(args) == 1 and "no portrait" in capsys.readouterr().err
    (tmp_path / "chars").mkdir(); (tmp_path / "chars" / "น้องเอิร์ธ.jpg").write_bytes(b"p")
    assert cj.main(args) == 0


def test_reshape_before_any_render(tmp_path, monkeypatch, capsys):
    """gotg-encore-s2 2026-11-20: 6+4 s failed in Flow, Fix wanted one 10 s scene -> cancel + a new job."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    j = job(shots=2, prod="prompt"); j["shots"][0]["seconds"], j["shots"][1]["seconds"] = 6, 4
    j["shots"][0]["state"] = j["shots"][1]["state"] = "packed"; cj.save(j)
    assert cj.main(["reshape", "t-1", "--shots", "1", "--seconds", "10"]) == 0
    j = cj.load("t-1")
    assert [(s["k"], s["seconds"], s["state"]) for s in j["shots"]] == [(1, 10, "pending")]
    assert "reshaped" in j["events"][-1]["msg"]
    cj.shot(j, 1)["state"] = "packed"; cj.ingest(j, 1, "/tmp/x.mp4"); cj.save(j)
    assert cj.main(["reshape", "t-1", "--shots", "2"]) == 1       # a file arrived: too late
    assert "already have" in capsys.readouterr().err


def test_gameplay_deliver_refuses_a_cut_end_card(tmp_path, monkeypatch, capsys):
    """ffr-swt-dec04 / sniper-elite3-sw 2026-11-20/21."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    monkeypatch.setattr(cj, "CLIP_LOG", str(tmp_path / "log.jsonl"))
    assert cj.main(["new", "g-2", "--mode", "gameplay", "--product", "Game", "--link", "https://s.shopee.co.th/x",
                    "--workdir", str(tmp_path / "w")]) == 0
    final = tmp_path / "f.mp4"; final.write_bytes(b"a"); cover = tmp_path / "c.jpg"; cover.write_bytes(b"c")
    monkeypatch.setattr(cj, "av_durations", lambda p: (20.0, 20.0))
    cut = {"ok": False, "hits": [{"t": 24.6, "text": "IPER ELITE", "side": "right"}]}
    monkeypatch.setattr(cj, "run", lambda cmd: (1, json.dumps(cut), "") if cmd[-2].endswith("endcard_check.py")
                        else (0, json.dumps({"ok": True}), ""))
    args = ["deliver", "g-2", "--final", str(final), "--hashtags", "#game", "--cover", str(cover), "--caption", "c", "--post-hook", "ใครเล่นเกมนี้จบแล้วต้องลองโหมดใหม่"]
    assert cj.main(args) == 1 and "IPER ELITE" in capsys.readouterr().err
    monkeypatch.setenv("ENDCARD_OK", "1")
    assert cj.main(args) == 0


def test_prompt_mode_end_to_end_needs_no_tap_and_no_ack(tmp_path, monkeypatch, capsys):
    """The whole 📝 path after Fix's rule: pack -> two replies -> ready (auto) -> assemble-check -> deliver gates."""
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    monkeypatch.setattr(cj, "tg", lambda *a, **k: {"message_id": 1})
    monkeypatch.setattr(cj, "last_frame", lambda video, out: open(out, "wb").close() or out)
    monkeypatch.setattr(cj, "ffprobe", lambda p: {"w": 720, "h": 1280, "dur": 8.0, "kbps": 3000, "has_audio": True})
    j = job(shots=2, mode="product", prod="prompt"); j["workdir"] = str(tmp_path); cj.save(j)
    for k in (1, 2):
        (tmp_path / f"shot{k}.txt").write_text("Product b-roll, no speech.", encoding="utf-8")
    assert cj.main(["pack", "t-1", "--no-send"]) == 0
    capsys.readouterr()
    for k in (1, 2):
        f = tmp_path / f"in{k}.mp4"; f.write_bytes(b"v%d" % k)
        assert cj.main(["ingest", "t-1", str(f), "--shot", str(k)]) == 0
        dst = json.loads(capsys.readouterr().out)["file"]
        assert cj.main(["ready", "t-1", str(k), "--raw", dst]) == 0
        capsys.readouterr()
    assert cj.main(["assemble-check", "t-1"]) == 0
    j = cj.load("t-1")
    assert cj.deliver_problems(j, {"flags": [], "v_dur": 16.0, "a_dur": 16.0},
                               {"headlines": [{"text": "x"}]}, "#a #b") == []
    assert cj.billed_credits(j) == [30, 30]


def test_endcard_rect_comes_from_the_jobs_build_timeline(tmp_path):
    """switch2-oblivion-rd 2026-11-22: the card's picture edge is only known to build_v5."""
    j = {"workdir": str(tmp_path)}
    assert cj.endcard_rect(j, "final.mp4") is None                       # no build yet
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "timeline_v5.json").write_text('{"segs": []}')
    assert cj.endcard_rect(j, "final.mp4") is None                       # older build_v5: no key
    (tmp_path / "work" / "timeline_v5.json").write_text('{"endcard_rect": [0, 348, 720, 750.0]}')
    assert cj.endcard_rect(j, "final.mp4") == "0,348,720,750"


def _vision_db(path, calls):
    """A state.db with the two tables vision_calls reads: (asked, answered or None) per call."""
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE messages (role TEXT, timestamp REAL, tool_calls TEXT, tool_call_id TEXT)")
    for i, (a, b) in enumerate(calls):
        c.execute("INSERT INTO messages VALUES ('assistant', ?, ?, NULL)",
                  (a, json.dumps([{"id": f"v{i}", "function": {"name": "vision_analyze"}}])))
        if b is not None:
            c.execute("INSERT INTO messages VALUES ('tool', ?, NULL, ?)", (b, f"v{i}"))
    c.execute("INSERT INTO messages VALUES ('assistant', 5, ?, NULL)",
              (json.dumps([{"id": "t1", "function": {"name": "terminal"}}]),))
    c.commit(); c.close()


def test_vision_calls_counts_this_jobs_calls_and_the_420s_hang(tmp_path):
    """switch2-oblivion-rd 2026-11-22: 13 vision calls, one hung to the 420 s tool deadline."""
    db = str(tmp_path / "state.db")
    _vision_db(db, [(10, 70), (100, 520), (600, None), (5000, 5050)])
    assert cj.vision_calls(0, 1000, db) == [(10, 70), (100, 520), (600, 1000)]
    assert cj.vision_calls(0, 1000, str(tmp_path / "none.db")) == []


def test_vision_budget_and_warning():
    g = {"mode": "gameplay", "shots": []}
    p = {"mode": "presenter", "shots": [{"attempts": [{"via": "auto"}]}, {"attempts": [{"via": "prompt"}]}]}
    assert cj.vision_budget(g) == 8 and cj.vision_budget(p) == 7
    assert cj.vision_warning({"calls": 7, "budget": 8, "min": 9}) is None
    assert "13/8" in cj.vision_warning({"calls": 13, "budget": 8, "min": 25})


def test_stage_marks_split_a_gameplay_timeline():
    """🎬 timing was one 'ทำคลิป 113' block (switch2-oblivion-rd); stage events split it."""
    def ev(hhmm, msg):
        return {"ts": f"2026-11-22T{hhmm}:00+07:00", "msg": msg}
    j = {"created": "2026-11-22T19:23:00+07:00", "started": "2026-11-22T19:23:00+07:00",
         "events": [ev("19:23", "created"), ev("19:33", "stage: footage"), ev("19:50", "stage: endcard"),
                    ev("20:16", "stage: vo"), ev("20:36", "stage: build"), ev("20:55", "stage: cover"),
                    ev("21:16", "delivered")]}
    tl = cj.timeline(j)
    assert tl["stages"] == [["เตรียม", 0], ["ทำคลิป", 10], ["footage", 17], ["endcard", 26], ["vo", 20],
                            ["build", 19], ["cover", 21]]
    assert tl["total_min"] == 113


# ---------------------------------------------------------------- board reply gate + VO rate (Fix 2026-11-23)
def hermes_db(path, rows):
    """A state.db with Hermes' messages columns the gate reads: (timestamp, role, content, tool_name)."""
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, tool_name TEXT, "
              "tool_calls TEXT, tool_call_id TEXT, timestamp REAL)")
    c.executemany("INSERT INTO messages (timestamp, role, content, tool_name) VALUES (?,?,?,?)", rows)
    c.commit(); c.close()
    return str(path)


def boarded(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setattr(cj, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(cj, "CHAR_DIR", str(tmp_path)); (tmp_path / "น้องมุก.jpg").write_bytes(b"p")
    assert cj.main(["intake", "b-1", "--product", "Cape"]) == 0
    assert cj.main(["board", "b-1", "--hook-id", "gadget-2"]) == 0
    sent = cj._epoch(cj.load("b-1")["board"]["sent"])
    monkeypatch.setattr(cj, "HERMES_DB", hermes_db(tmp_path / "state.db", [(sent + dt, *r) for dt, *r in rows]))
    ref = tmp_path / "r.jpg"; ref.write_bytes(b"r")
    return ["new", "b-1", "--mode", "presenter", "--product", "Cape", "--shots", "1", "--ref", str(ref),
            "--character", "น้องมุก"]


def test_a_message_queued_before_the_board_is_not_its_approval(tmp_path, monkeypatch, capsys):
    """plaid-shoulder-blanket 2026-11-23: 'ไอยูทำใน flow ให้เลยนะ' (01:02) replayed after the board asks timed out."""
    args = boarded(tmp_path, monkeypatch, [(-1020, "user", "ไอยูทำใน flow ให้เลยนะ", None),
                                           (600, "tool", json.dumps({"responses": [{"status": "unanswered"}]}), "clarify")])
    assert cj.main(args) == 1 and "no reply from Fix since the board" in capsys.readouterr().err
    assert cj.load("b-1")["stage"] == "intake"


def test_a_tap_after_the_board_lets_new_through_and_is_recorded(tmp_path, monkeypatch, capsys):
    args = boarded(tmp_path, monkeypatch, [(-1020, "user", "ไอยูทำใน flow ให้เลยนะ", None),
                                           (300, "tool", json.dumps({"responses": [{"status": "answered",
                                            "user_response": "ผ่าน + ให้ไอยูกด 🤖"}]}), "clarify")])
    assert cj.main(args) == 0
    b = cj.load("b-1")["board"]
    assert b["answer"].endswith("ผ่าน + ให้ไอยูกด 🤖") and b["answer_at"]


def test_gameplay_new_needs_no_board(tmp_path, monkeypatch):
    monkeypatch.setattr(cj, "DIR", str(tmp_path))
    assert cj.main(["new", "g-9", "--mode", "gameplay", "--product", "G", "--workdir", str(tmp_path / "w")]) == 0


def vo_job(tmp_path, seconds, lines):
    j = cj.new_job("v-1", "presenter", "Tee", "https://s.shopee.co.th/x", len(seconds), ["/tmp/ref.jpg"],
                   workdir=str(tmp_path), character="น้องเนย", seconds=",".join(map(str, seconds)))
    for k, line in enumerate(lines, 1):
        (tmp_path / f"shot{k}.txt").write_text(f'Scene.\nAudio (Thai voiceover): "{line}"\nmore', encoding="utf-8")
    return j


def test_a_line_too_long_for_its_shot_is_refused_before_credits(tmp_path):
    """genme-fly-duck-tee 2026-11-23 shot 2: 49 chars in 4 s = 12.2/s, the link line was not spoken."""
    j = vo_job(tmp_path, [6, 4], ["เสื้อยืดสีขาวตัวนี้ พิมพ์เล็กที่อก ชิ้นเดียวแมตช์ได้หลายลุค ลองดูสิ",
                                  "ดูด้านหลังนะ เป็ดตัวใหญ่เต็มหลัง ลิงก์อยู่ใต้คลิปนะ"])
    assert cj.vo_rate(j, 2) == (49, 4, 12.2)
    cj.vo_rate_check(j, 1)                                     # 64 chars / 6 s = 10.7: fine
    with pytest.raises(cj.Refused, match=r"12.2/s > 11.5/s.*make the shot 5 s"):
        cj.vo_rate_check(j, 2)
    cj.set_production(j, "prompt")
    with pytest.raises(cj.Refused, match="Flow drops the end"):
        cj.cmd_pack(j, None, True)                             # pack (and reserve) run the same check


def test_vo_rate_skips_silent_shots_and_respects_the_override(tmp_path, monkeypatch):
    j = vo_job(tmp_path, [6], ["x" * 80])
    (tmp_path / "shot1.txt").write_text("hands fold the cape, no speech", encoding="utf-8")
    assert cj.vo_rate(j, 1) is None
    (tmp_path / "shot1.txt").write_text('Audio (Thai voiceover): "' + "ก" * 80 + '"', encoding="utf-8")
    monkeypatch.setenv("VO_DENSE_OK", "1")
    cj.vo_rate_check(j, 1)


def test_board_stamped_after_the_answer_is_refused(tmp_path, monkeypatch, capsys):
    """Order is board message -> `clipjob.py board` -> clarify: stamping after his tap leaves nothing newer."""
    args = boarded(tmp_path, monkeypatch, [(-60, "tool", json.dumps({"responses": [{"status": "answered",
                                            "user_response": "ผ่าน เริ่ม gen (≈30 เครดิต)"}]}), "clarify")])
    assert cj.main(args) == 1 and "no reply from Fix since the board" in capsys.readouterr().err


def test_a_revise_answer_is_not_approval(tmp_path, monkeypatch, capsys):
    args = boarded(tmp_path, monkeypatch, [(120, "tool", json.dumps({"responses": [{"status": "answered",
                                            "user_response": "แก้ storyboard"}]}), "clarify")])
    assert cj.main(args) == 1 and "revise / cancel" in capsys.readouterr().err


def test_pack_no_start_frame_says_so_and_sends_no_frame(tmp_path, monkeypatch):
    """ps2-hdd-175-pres 2026-11-24: a re-pack meant to test 'no start frame' still told Fix to attach one."""
    calls = []
    monkeypatch.setattr(cj, "tg", lambda m, d, files=None: calls.append((m, d, files)) or {"message_id": 1})
    monkeypatch.setattr(cj, "start_frame_for", lambda j, k: {"file": str(tmp_path / "last.jpg"), "from": 1,
                                                             "faceless": [], "unchecked": False})
    j = job(2, prod="prompt"); j["workdir"] = str(tmp_path)
    (tmp_path / "shot2.txt").write_text("Start exactly on the attached last-frame image. She plugs it in.",
                                        encoding="utf-8")
    cj.shot(j, 1).update({"state": "approved", "file": str(tmp_path / "s1.mp4")})
    (tmp_path / "s1.mp4").write_bytes(b"x")
    with pytest.raises(cj.Refused, match="no-start-frame"):
        cj.cmd_pack(j, 2, False, no_start_frame=True)
    (tmp_path / "shot2.txt").write_text("She plugs it in.", encoding="utf-8")
    cj.cmd_pack(j, 2, False, no_start_frame=True)
    texts = " ".join(d.get("text", "") for m, d, f in calls if m == "sendMessage")
    assert "รอบนี้ไม่ต้องแนบ" in texts and "แนบรูปเฟรมเริ่มที่ส่งไปเมื่อกี้" not in texts
    assert not [c for c in calls if c[0] == "sendPhoto" and "เฟรมเริ่ม" in (c[1].get("caption") or "")]
    calls.clear()
    sent = cj.cmd_pack(j, 2, False)                             # the default still chains the frame
    texts = " ".join(d.get("text", "") for m, d, f in calls if m == "sendMessage")
    assert "แนบรูปเฟรมเริ่มที่ส่งไปเมื่อกี้" in texts
    assert "--no-start-frame" in sent[0]["warn"]                # ...and says the prompt never asks for it
    (tmp_path / "shot2.txt").write_text("Start exactly on the attached last-frame image. She plugs it in.",
                                        encoding="utf-8")
    assert "warn" not in cj.cmd_pack(j, 2, False)[0]


def test_ingest_records_the_real_credits_when_given(tmp_path):
    """A 📝 shot Fix rendered on Omni 1.1 costs 9, not the 1.2 estimate of 18 (ps2-hdd-175-pres 2026-11-24)."""
    j = job(2, prod="prompt"); j["workdir"] = str(tmp_path)
    cj.shot(j, 1)["seconds"] = 6
    cj.ingest(j, 1, str(tmp_path / "a.mp4"), credits=9)
    assert cj.shot(j, 1)["attempts"][-1]["credits"] == 9 and "credits_est" not in cj.shot(j, 1)["attempts"][-1]
    cj.shot(j, 2)["seconds"] = 6
    cj.ingest(j, 2, str(tmp_path / "b.mp4"))
    assert cj.shot(j, 2)["attempts"][-1] == {**cj.shot(j, 2)["attempts"][-1], "credits": 18, "credits_est": True}


def test_board_needs_the_hook_id_and_keeps_every_boarded_hook(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    assert cj.main(["intake", "h-1", "--product", "Game", "--mode", "presenter"]) == 0
    assert cj.main(["board", "h-1"]) == 1
    assert "--hook-id" in capsys.readouterr().err
    assert cj.main(["board", "h-1", "--hook-id", "เบื่อเกม"]) == 1           # an id, not the line
    assert cj.main(["board", "h-1", "--hook-id", "game-2"]) == 0
    assert cj.main(["board", "h-1", "--hook-id", "custom-metroid-1"]) == 0   # Fix rewrote the hook: v2 board
    b = cj.load("h-1")["board"]
    assert b["hook_id"] == "custom-metroid-1"
    assert [h["id"] for h in b["hooks"]] == ["game-2", "custom-metroid-1"]   # the first pick still counts as used


def test_post_hook_must_be_new(tmp_path, monkeypatch):
    """Fix 2026-11-26: a 🪝 copy button with a NEW hook — never a hooks.md line or an earlier post hook."""
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"date": "2026-11-24", "product": "HUAWEI WATCH FIT 5 Series", "sha256": "aa",
                               "post_hook": "HUAWEI WATCH FIT 5 วัดหัวใจได้ทั้งวัน ไม่ต้องชาร์จบ่อย",
                               "notes": "job hw-fit5 production=auto"}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(cj, "CLIP_LOG", str(log))
    game = {"job": "m-1", "product": "SWITCH-2 METROID RAVENOUS (GAME)"}
    assert "missing --post-hook" in cj.post_hook_problems("", game)[0]
    assert any("retired" in p for p in cj.post_hook_problems("เบื่อเกมเดิมๆ อยู่ใช่ไหม", game))
    assert "hooks.md" in cj.post_hook_problems("แฟน Metroid ภาคนี้ต้องมีติดเครื่อง", game)[0]   # template, name filled
    assert "hooks.md" in cj.post_hook_problems("สายเกม RPG ฟังทางนี้", game)[0]                 # retired, other genre
    assert cj.post_hook_problems("Samus กลับมาแล้ว รอบนี้ต้องหนีจากดาวที่ทั้งดาวล่าเธอ", game) == []
    assert cj.post_hook_problems("ลด 50% วันนี้", game)                                         # price wording
    watch = {"job": "watch-2", "product": "HUAWEI WATCH FIT 5 Series สมาร์ทวอทช์"}
    assert cj.post_hook_problems("จอใหญ่ขึ้น ใส่วิ่งแล้วเบาข้อมือ HUAWEI WATCH FIT 5", watch) == []  # same product, new line
    assert "2026-11-24" in cj.post_hook_problems("HUAWEI WATCH FIT 5 วัดหัวใจได้ทั้งวัน ไม่ต้องชาร์จบ่อยเลย", watch)[0]
    same = {"job": "hw-fit5", "product": "HUAWEI WATCH FIT 5 Series"}                       # its own rerun / revision
    assert cj.post_hook_problems("HUAWEI WATCH FIT 5 วัดหัวใจได้ทั้งวัน ไม่ต้องชาร์จบ่อย", same) == []


def test_deliver_refuses_without_a_post_hook_and_logs_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cj, "DIR", str(tmp_path)); monkeypatch.setenv("CLIPJOB_NO_TG", "1")
    monkeypatch.setattr(cj, "FINALS_DIR", str(tmp_path / "finals"))
    log = tmp_path / "clip-log.jsonl"; monkeypatch.setattr(cj, "CLIP_LOG", str(log))
    assert cj.main(["new", "g-9", "--mode", "gameplay", "--product", "Game", "--link", "https://s.shopee.co.th/x",
                    "--workdir", str(tmp_path / "w")]) == 0
    final = tmp_path / "f.mp4"; final.write_bytes(b"a"); cover = tmp_path / "c.jpg"; cover.write_bytes(b"c")
    monkeypatch.setattr(cj, "av_durations", lambda p: (20.0, 20.0))
    monkeypatch.setattr(cj, "run", lambda cmd: (0, json.dumps({"ok": True}), ""))
    args = ["deliver", "g-9", "--final", str(final), "--hashtags", "#game", "--cover", str(cover), "--caption", "c"]
    assert cj.main(args) == 1 and "missing --post-hook" in capsys.readouterr().err
    assert cj.main([*args, "--post-hook", "ปลูกผักขายในหมู่บ้านกลางป่า"]) == 0
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["post_hook"] == "ปลูกผักขายในหมู่บ้านกลางป่า"
    assert cj.load("g-9")["delivery"]["mirror"]["post_hook"] == "ปลูกผักขายในหมู่บ้านกลางป่า"
