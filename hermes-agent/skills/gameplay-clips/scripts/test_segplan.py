"""segplan: frame-exact layout of Hermes' picks, and the refusals that replace hand math."""
import importlib.util
import json
import os

_spec = importlib.util.spec_from_file_location(
    "segplan", os.path.join(os.path.dirname(os.path.abspath(__file__)), "segplan.py"))
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

WINS = [(20.12, 21.62), (22.12, 23.88), (24.12, 25.37), (27.88 + 0.23, 35.38), (35.62, 39.88)]


def table(tmp_path, wash=True, rebase=0.0):
    t = {"src": "/w/src_clean.mp4", "rebase": rebase, "speech_vtt": "/w/src_clean_speech.vtt",
         "windows": [{"n": i, "start": a, "end": b, "dur": round(b - a, 2)} for i, (a, b) in enumerate(WINS, 1)]}
    if wash:
        t["wash"] = [[27.85, 28.11]]
    p = tmp_path / "t_windows.json"
    p.write_text(json.dumps(t))
    return str(p)


def run(tmp_path, capsys, *args, **kw):
    rc = sp.main([table(tmp_path, **kw), *args])
    return rc, capsys.readouterr().out


def segs_of(out):
    return json.loads([ln for ln in out.splitlines() if ln.startswith("[")][-1])


def test_zelda_16s_does_not_fit_and_names_the_dur(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, "--dur", "16", "--picks", "W4@31.9:hero,W1,W2,W3,W4,W5")
    assert rc == 1 and "DOES NOT FIT" in out and "15.5 s" in out


def test_zelda_15_5_fits_frame_exact(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, "--dur", "15.5", "--picks", "W4@31.9:hero,W1,W2,W3,W4,W5")
    assert rc == 0
    segs = segs_of(out)
    frames = [round(s["dur"] * 30) for s in segs]
    assert sum(frames) == 465 and all(abs(s["dur"] * 30 - f) < 0.01 for s, f in zip(segs, frames))
    assert segs[0]["mode"] == "hero" and segs[0]["in"] >= 31.9
    w4 = segs[4]
    assert w4["in"] >= 28.11 and w4["in"] + w4["dur"] <= 31.9 + 1e-6     # stops at the hero's pin
    last = segs[-1]
    assert last["dur"] >= 4.0 and last["in"] + last["dur"] <= 39.88
    for s in segs:
        a, b = next((a, b) for a, b in WINS if a <= s["in"] < b)
        assert s["in"] >= a and s["in"] + s["dur"] <= b + 1e-6
        assert s["snap"] is False and "audio_in" not in s


def test_old_table_refused_with_rerun_command(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, "--dur", "15.5", "--picks", "W1", wash=False)
    assert rc == 2 and "windows.py src_clean.mp4 --vtt src_clean_speech.vtt" in out


def test_rebase_sets_master_audio(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, "--dur", "6", "--picks", "W4@31.9:hero,W5", rebase=10.0)
    assert rc == 0
    for s in segs_of(out):
        assert s["audio_src"] == "master" and abs(s["audio_in"] - (s["in"] - 10.0)) < 1e-6


def test_short_end_card(tmp_path, capsys):
    ec = tmp_path / "ec.json"
    ec.write_text(json.dumps({"seg": {"src": "trailer", "in": 150.85, "dur": 1.9, "crop": [533, 301, 892, 440]}}))
    rc, out = run(tmp_path, capsys, "--dur", "12", "--picks", "W4@31.9:hero,W5", "--endcard", str(ec))
    assert rc == 3 and "END CARD TOO SHORT" in out and "0.30 s" in out
    rc, out = run(tmp_path, capsys, "--dur", "8", "--picks", "W4@31.9:hero,W5", "--endcard", str(ec), "--short-card-ok")
    assert rc == 0 and segs_of(out)[-1]["endcard"] is True and abs(segs_of(out)[-1]["dur"] - 1.9) < 1e-6


def test_null_crop_card_needs_wide(tmp_path, capsys):
    ec = tmp_path / "ec.json"
    ec.write_text(json.dumps({"problem": "40 in the title block", "seg": {"src": "trailer", "in": 50.0, "dur": 4.5, "crop": None}}))
    rc, out = run(tmp_path, capsys, "--dur", "10", "--picks", "W4@31.9:hero,W5", "--endcard", str(ec))
    assert rc == 3 and "REFUSED" in out
    rc, out = run(tmp_path, capsys, "--dur", "10", "--picks", "W4@31.9:hero,W5", "--endcard", str(ec), "--endcard-wide")
    last = segs_of(out)[-1]
    assert rc == 0 and last["wide"] is True and "crop" not in last


def test_write_merges_only_segs_and_dur(tmp_path, capsys):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"dur": 20, "fps": 30, "cta": {"text": "Link below!"}, "segs": []}))
    rc, _ = run(tmp_path, capsys, "--dur", "15.5", "--picks", "W4@31.9:hero,W1,W2,W3,W4,W5", "--write", str(plan))
    p = json.loads(plan.read_text())
    assert rc == 0 and p["dur"] == 15.5 and len(p["segs"]) == 6 and p["cta"] == {"text": "Link below!"}


def two_tables(tmp_path):
    """gta6-codebox-gp2 2026-11-25: hero from the raw clip, windows from two square crops of the vertical clips."""
    raw = {"src": "/w/tr_np20.mp4", "rebase": 0.0, "wash": [], "speech": [],
           "windows": [{"n": 1, "start": 10.38, "end": 13.62, "dur": 3.24}]}
    a = {"src": "/w/winsqa_np20.mp4", "rebase": 0.0, "wash": [], "speech": [],
         "windows": [{"n": 1, "start": 0.0, "end": 7.75, "dur": 7.75}, {"n": 2, "start": 10.25, "end": 13.62, "dur": 3.37}]}
    b = {"src": "/w/winsqa_np19.mp4", "rebase": 0.0, "wash": [], "speech": [[14.0, 19.0]],
         "windows": [{"n": 1, "start": 0.0, "end": 8.0, "dur": 8.0}, {"n": 2, "start": 10.0, "end": 12.4, "dur": 2.4}]}
    out = []
    for name, t in (("raw", raw), ("a", a), ("b", b)):
        p = tmp_path / f"{name}_windows.json"
        p.write_text(json.dumps(t))
        out.append(str(p))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"trailer": "/w/tr_np20.mp4", "segs": [], "dur": 0}))
    return out, str(plan)


def test_several_tables_set_src_and_audio_per_source(tmp_path, capsys):
    (raw, a, b), plan = two_tables(tmp_path)
    rc = sp.main([raw, a, b, "--dur", "15", "--picks", "A:W1@10.4:hero,B:W1@0.1,B:W1@3.85,C:W1@0.1,C:W2",
                  "--write", plan])
    out = capsys.readouterr().out
    assert rc == 0, out
    segs = json.load(open(plan))["segs"]
    assert segs[0]["src"] == "trailer" and "audio_src" not in segs[0]          # the plan's own trailer
    assert [s["src"] for s in segs[1:]] == ["/w/winsqa_np20.mp4"] * 2 + ["/w/winsqa_np19.mp4"] * 2
    assert segs[1]["audio_src"] == "/w/winsqa_np20.mp4"
    # one source block = one continuous music bed: the second seg's audio picks up where the first ended
    assert abs(segs[2]["audio_in"] - (segs[1]["audio_in"] + segs[1]["dur"])) < 1e-3
    assert segs[3]["audio_in"] == segs[3]["in"]                                # a new block starts at its picture
    assert round(sum(s["dur"] for s in segs) * 30) == 450


def test_continuous_bed_never_runs_into_that_sources_speech(tmp_path, capsys):
    (raw, a, b), plan = two_tables(tmp_path)
    rc = sp.main([raw, a, b, "--dur", "10", "--picks", "A:W1@10.4:hero,C:W2,C:W1@0.1", "--write", plan])
    out = capsys.readouterr().out
    assert rc == 0, out
    segs = json.load(open(plan))["segs"]
    s1, s2 = segs[1], segs[2]
    assert s1["audio_in"] + s1["dur"] + s2["dur"] > 14.0             # the bed would reach C's speech at 14 s
    assert s2["audio_in"] == s2["in"] and "music jump at seg 2" in out


def test_one_table_keeps_the_old_output(tmp_path, capsys):
    rc, out = run(tmp_path, capsys, "--dur", "15.5", "--picks", "A:W4@31.9:hero,W1,W2,W3,W4,W5")
    assert rc == 0 and all(s["src"] == "trailer" and "audio_in" not in s for s in segs_of(out))


def test_unknown_table_letter(tmp_path, capsys):
    import pytest
    with pytest.raises(SystemExit, match="table B"):
        run(tmp_path, capsys, "--dur", "15.5", "--picks", "B:W1")
