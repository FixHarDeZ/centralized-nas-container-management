import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("clip_heartbeat", os.path.join(HERE, "clip_heartbeat.py"))
hb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hb)

JOB = {"job": "huawei-watchfit5", "status": "open", "shots": [{"k": 1, "state": "approved"}, {"k": 2, "state": "approved"}]}


def call(name, args="", ts=0):
    return {"role": "assistant", "content": "", "tool_name": None, "timestamp": ts,
            "tool_calls": json.dumps([{"function": {"name": name, "arguments": args}}])}


def result(name, ts):
    return {"role": "tool", "content": "{}", "tool_calls": None, "tool_name": name, "timestamp": ts}


def final(ts):
    return {"role": "assistant", "content": "ส่งแล้วค่ะ", "tool_calls": None, "tool_name": None, "timestamp": ts}


def test_quiet_mid_turn_sends_one_line_with_the_stage():
    msgs = [result("execute_code", 1000), call("execute_code", "x", 990),
            call("terminal", '{"command": "python3 send_status.py \\"เริ่ม post\\""}', 100)]
    line, st = hb.decide(1000 + 60, JOB, msgs, {})
    assert line and "post" in line and "เงียบมา 16 นาที" in line and st["sent"] == 1060
    assert hb.decide(1000 + 60, JOB, msgs, {}, sent=900)[0] is None    # send_photo stamped 2.7 min ago
    assert hb.decide(1200, JOB, msgs, st)[0] is None                  # its own line counts as seen


def test_recent_status_line_means_no_heartbeat():
    msgs = [result("terminal", 1000), call("terminal", "send_status.py ok", 900)]
    assert hb.decide(1100, JOB, msgs, {})[0] is None


def test_turn_ended_or_clarify_waits_on_fix():
    assert hb.decide(5000, JOB, [final(100)], {})[0] is None
    assert hb.decide(5000, JOB, [call("clarify", "{}", 100)], {})[0] is None


def test_no_open_job_no_line():
    assert hb.open_job([{**JOB, "status": "delivered"}]) is None
    assert hb.decide(5000, None, [result("terminal", 4990)], {})[0] is None


def test_stuck_turn_is_reported_once():
    msgs = [call("vision_analyze", "{}", 0)]
    line, st = hb.decide(25 * 60, JOB, msgs, {})
    assert line.startswith("⚠️") and "อ่านภาพ" in line
    assert hb.decide(30 * 60, JOB, msgs, st)[0] is None


def test_stage_names():
    assert hb.stage_of({"shots": [{"k": 1, "state": "submitted"}]}) == "gen ช็อต 1"
    assert hb.stage_of({"stage": "footage", "shots": []}) == "footage"
    assert hb.stage_of({"stage": "intake", "shots": []}) == "เตรียมงาน"


def test_no_cjk_in_lines():
    import send_status
    msgs = [result("browser_exec", 1000), call("browser_exec", "", 990)]
    line, _ = hb.decide(1000 + 16 * 60, JOB, msgs, {})
    assert line and send_status.cjk_hits(line) == []


def test_scratch_sender_counts_as_seen():
    msgs = [result("terminal", 1000), call("terminal", '{"command": "python3 sendphoto_ps2hdd.py ref.jpg"}', 950)]
    assert hb.decide(1000 + 10 * 60, JOB, msgs, {})[0] is None
