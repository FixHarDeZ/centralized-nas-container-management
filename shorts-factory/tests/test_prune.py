import json
import os
from datetime import datetime, timedelta

from app import history, prune

NOW = datetime(2026, 10, 30, 12, 0)


def _clip(folder, stem, title, days_old):
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in (".mp4", ".txt", ".srt"):
        path = folder / f"{stem}{suffix}"
        path.write_text(f"{title}\n\nคำอธิบาย" if suffix == ".txt" else "x", encoding="utf-8")
        stamp = (NOW - timedelta(days=days_old)).timestamp()
        os.utime(path, (stamp, stamp))
    return folder / f"{stem}.mp4"


def _published(tmp_path, monkeypatch, *titles):
    path = tmp_path / "history.json"
    path.write_text(json.dumps([{"video_id": f"v{i}", "title": t} for i, t in enumerate(titles)]),
                    encoding="utf-8")
    monkeypatch.setattr(history, "PATH", path)


def test_an_uploaded_clip_loses_its_mp4_after_seven_days(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(prune, "OUTPUT_DIR", out)
    _published(tmp_path, monkeypatch, "เก่า", "ใหม่")
    old = _clip(out, "20261020-0800-เก่า", "เก่า", days_old=10)
    new = _clip(out, "20261028-0800-ใหม่", "ใหม่", days_old=2)

    removed = prune.run(now=NOW)

    assert removed == [old]
    assert not old.exists() and new.exists()
    # backfill rebuilds Manifests from these; they are a few KB each.
    assert old.with_suffix(".txt").exists() and old.with_suffix(".srt").exists()


def test_a_clip_never_uploaded_is_kept_however_old(tmp_path, monkeypatch):
    """English Clips are uploaded by hand from /volume1/shorts/en and never
    reach history.json — the file on the NAS is the only copy."""
    out = tmp_path / "out"
    monkeypatch.setattr(prune, "OUTPUT_DIR", out)
    _published(tmp_path, monkeypatch)
    th = _clip(out, "20261001-0800-ไม่ได้อัป", "ไม่ได้อัป", days_old=29)
    en = _clip(out / "en", "20261001-0800-english", "english", days_old=29)

    assert prune.run(now=NOW) == []
    assert th.exists() and en.exists()


def test_the_english_folder_is_pruned_too(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(prune, "OUTPUT_DIR", out)
    _published(tmp_path, monkeypatch, "english")
    en = _clip(out / "en", "20261001-0800-english", "english", days_old=29)

    assert prune.run(now=NOW) == [en]


def test_folders_that_are_not_a_locale_are_left_alone(tmp_path, monkeypatch):
    """Product Clips are posted by hand, Footage cost Flow credits."""
    out = tmp_path / "out"
    monkeypatch.setattr(prune, "OUTPUT_DIR", out)
    _published(tmp_path, monkeypatch, "ของ")
    shop = _clip(out / "shop" / "p261014152504", "clip", "ของ", days_old=29)
    footage = _clip(out / "footage" / "c1", "c00", "ของ", days_old=29)

    assert prune.run(now=NOW) == []
    assert shop.exists() and footage.exists()


def test_a_clip_behind_a_live_upload_button_is_kept(tmp_path, monkeypatch):
    """A re-render shares the published title; its button must still work."""
    out = tmp_path / "out"
    monkeypatch.setattr(prune, "OUTPUT_DIR", out)
    _published(tmp_path, monkeypatch, "ซ้ำ")
    held = _clip(out, "20261001-0800-ซ้ำ", "ซ้ำ", days_old=29)
    state = {"uploads": {"c1": {"clip": str(held), "message_id": 42}}}

    assert prune.run(now=NOW, keep=prune.held(state)) == []
    assert held.exists()


def test_a_spent_upload_entry_does_not_hold_its_clip(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(prune, "OUTPUT_DIR", out)
    _published(tmp_path, monkeypatch, "อัปแล้ว")
    clip = _clip(out, "20261001-0800-อัปแล้ว", "อัปแล้ว", days_old=29)
    state = {"uploads": {"c1": {"clip": str(clip), "message_id": None}},
             "last_clip": str(clip), "upload_message_id": None}

    assert prune.run(now=NOW, keep=prune.held(state)) == [clip]


def test_due_once_a_day():
    assert prune.due({}, NOW)
    assert not prune.due({"last_prune": "2026-10-30"}, NOW)
    assert prune.due({"last_prune": "2026-10-29"}, NOW)
