"""Delete the mp4 of a Clip once it is on YouTube and a week old.

Nothing else in /output is ever removed by the bot, and at ~100 Clips a month
the folder only grows. What goes is the video and nothing more:

- only a Clip whose title is in history.json, i.e. one the bot uploaded. An
  English Clip is uploaded by hand from /volume1/shorts/en and never reaches
  history, so the file here is its only copy and it stays;
- only the mp4 (and the cover JPEG next to it). The `.txt` and `.srt` are a
  few KB and are what `app.backfill` rebuilds a Manifest from;
- only the Locale folders, non-recursively: `shop/`, `footage/` and `bgm/`
  hold things that cost a human time or Flow credits;
- never a file an upload button still points at. A re-render shares the
  published title, and its button must not end in "file not found".

Matched on the title in the `.txt`, as `app.backfill` does: no Manifest
records the output path. Runs once a day off the poll loop, like snapshots.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from app import history, locales

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))
KEEP_DAYS = int(os.environ.get("CLIP_KEEP_DAYS", "7"))


def due(state: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return state.get("last_prune") != now.date().isoformat()


def held(state: dict) -> set[Path]:
    """Clips an upload button on screen still points at."""
    paths = {
        entry.get("clip") for entry in (state.get("uploads") or {}).values()
        if entry.get("message_id")
    }
    # The oldest buttons carry no clip id and upload whatever `last_clip` is.
    if state.get("upload_message_id"):
        paths.add(state.get("last_clip"))
    return {Path(p) for p in paths if p}


def _title(mp4: Path) -> str:
    try:
        return mp4.with_suffix(".txt").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def run(now: datetime | None = None, keep: set[Path] = frozenset()) -> list[Path]:
    """Remove what has aged out; return the mp4s removed."""
    cutoff = ((now or datetime.now()) - timedelta(days=KEEP_DAYS)).timestamp()
    published = {e.get("title") for e in history.load() if e.get("video_id") and e.get("title")}
    removed = []
    for code in locales.codes():
        folder = OUTPUT_DIR / locales.get(code)["subdir"]
        if not folder.is_dir():
            continue
        for mp4 in sorted(folder.glob("*.mp4")):
            if mp4 in keep or mp4.stat().st_mtime > cutoff or _title(mp4) not in published:
                continue
            try:
                mp4.unlink()
                mp4.with_suffix(".jpg").unlink(missing_ok=True)
            except OSError:
                logger.exception("ลบ %s ไม่ได้", mp4)
                continue
            removed.append(mp4)
    if removed:
        logger.info("ลบ mp4 ที่อัปแล้วเกิน %d วัน %d ไฟล์", KEEP_DAYS, len(removed))
    return removed
