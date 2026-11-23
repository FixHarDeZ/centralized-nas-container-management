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
