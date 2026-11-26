import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf


def _setup(tmp_path, monkeypatch, rows, jobs=()):
    log = tmp_path / "clip-log.jsonl"
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    jd = tmp_path / "jobs"
    jd.mkdir()
    for j in jobs:
        (jd / f"{j['job']}.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(perf, "CLIP_LOG", str(log))
    monkeypatch.setattr(perf, "PERF_LOG", str(tmp_path / "perf-log.jsonl"))
    monkeypatch.setattr(perf, "JOBS_DIR", str(jd))


def _pick(capsys, cands, category="game"):
    a = types.SimpleNamespace(category=category, prefix=None, candidates=",".join(cands))
    assert perf.cmd_pick(a) == 0
    return json.loads(capsys.readouterr().out)


G = [f"game-{i}" for i in range(1, 10)]


def test_recent_window_counts_only_the_same_family(tmp_path, monkeypatch, capsys):
    """2026-11-26: the game category's last rows were gameplay gph-N, so presenter game-N was never excluded."""
    rows = [{"date": "2026-11-01", "category": "game", "hook_id": h} for h in ("game-1", "game-3", "game-4")]
    rows += [{"date": "2026-11-20", "category": "game", "hook_id": f"gph-{i}"} for i in (6, 8, 9)]
    _setup(tmp_path, monkeypatch, rows)
    got = _pick(capsys, G)
    assert got["excluded_recent"] == ["game-4", "game-3", "game-1"]
    assert got["pick"] == "game-2"                      # never used -> most eligible


def test_a_boarded_hook_counts_as_used_even_when_the_row_logged_a_custom_id(tmp_path, monkeypatch, capsys):
    """game-2 went on the gotg and metroid boards, Fix rewrote it, the rows logged custom-*: it never aged."""
    rows = [{"date": f"2026-11-{i + 1:02d}", "category": "game", "hook_id": f"game-{i}"} for i in range(1, 10) if i != 2]
    rows.append({"date": "2026-11-20", "category": "game", "hook_id": "custom-gotg-encore-1"})
    jobs = [{"job": "gotg", "board": {"sent": "2026-11-20T12:30:00+07:00", "hooks": [
                {"id": "game-2", "at": "2026-11-20T12:17:00+07:00"},
                {"id": "custom-gotg-encore-1", "at": "2026-11-20T12:30:00+07:00"}]}},
            {"job": "old", "events": [{"ts": "2026-11-14T20:18:40+07:00",
                                        "msg": "note: storyboard approved (2x10s, hook game-2); prompts written"}]}]
    _setup(tmp_path, monkeypatch, rows, jobs)
    got = _pick(capsys, G)
    assert "game-2" in got["excluded_recent"] and got["pick"] == "game-1"


def test_small_family_keeps_two_eligible(tmp_path, monkeypatch, capsys):
    cands = [f"home-{i}" for i in range(1, 7)]
    rows = [{"date": f"2026-11-1{i}", "category": "home", "hook_id": h} for i, h in enumerate(cands)]
    _setup(tmp_path, monkeypatch, rows)
    got = _pick(capsys, cands, "home")
    assert len(got["excluded_recent"]) == 4 and got["pick"] == "home-1"


def test_hooks_md_game_family_has_no_retired_wording():
    ids = perf.hook_ids_from_md("game", None)
    assert ids == G
    with open(perf.HOOKS_MD, encoding="utf-8") as f:
        text = f.read()
    table = text[text.index("| `game-1` |"):text.index("ถ้อยคำที่เลิกใช้แล้ว")]
    assert "จำเจ" not in table and "เบื่อ" not in table
