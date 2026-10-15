"""Storyboard Studio packs: the maths and the files behind 🎞 Studio.

Flow's Storyboard Studio makes the pictures. This module decides how many 8s
shots each Flow Card needs (from narration measured before planning), keeps
the pack the dashboard shows, and cuts the one stitched export the human
brings back into per-Card footage. Pure apart from ffmpeg and the filesystem.
The dashboard imports it, so `app.render` (Pillow, edge-tts) is imported
only inside the functions that need it. See
docs/superpowers/specs/2026-10-15-storyboard-studio-pack-design.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

SHOT_SECONDS = 8.0
MARGIN = 0.5       # join silence + voice tail inside one shot
TOLERANCE = 0.5    # export length vs shots × 8
TOKEN = re.compile(r"^[a-f0-9]{12}$")
CLIP_ID = re.compile(r"^\d{8}-\d{6}-\d{3}(-\d+)?$")  # manifest.start bumps a collision to `-<n>`


def spans(starts: list[float], total: float, tail_pad: float) -> list[float]:
    """Seconds each Card is on screen; the last one runs past the narration."""
    out = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
    out.append(total - starts[-1] + tail_pad)
    return out


def shots_for(span: float) -> int:
    return max(1, math.ceil((span + MARGIN) / SHOT_SECONDS - 1e-9))


def pending_cards(sources: list[str], have: set[int]) -> list[int]:
    """Flow Cards that still need footage from Flow."""
    return [i for i, source in enumerate(sources) if source == "flow" and i not in have]


def shot_map(card_spans: list[float], pending: list[int]) -> dict[int, int]:
    return {i: shots_for(card_spans[i]) for i in pending}


def total_shots(shots: dict[int, int]) -> int:
    return sum(shots.values())


def credits(total: int) -> int:
    return total * int(os.environ.get("FLOW_CREDITS_PER_SHOT", "12"))


def new_token() -> str:
    return secrets.token_hex(6)


def fits(duration: float, total: int) -> bool:
    return abs(duration - total * SHOT_SECONDS) <= TOLERANCE + 1e-9


def shot_length(duration: float, total: int, even: bool) -> float:
    return duration / total if even else SHOT_SECONDS


# --- files -------------------------------------------------------------------

def _base() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "studio"


def root(clip_id: str) -> Path:
    if not CLIP_ID.fullmatch(clip_id or ""):
        raise ValueError(f"clip id ไม่ถูกต้อง: {clip_id!r}")
    return _base() / clip_id


def segment_path(clip_id: str, card: int) -> Path:
    return root(clip_id) / "segments" / f"c{card:02d}.mp4"


def have_segments(clip_id: str, count: int) -> set[int]:
    return {i for i in range(count) if segment_path(clip_id, i).is_file()}


def write_pack(clip_id: str, pack: dict, markdown: str) -> None:
    where = root(clip_id)
    where.mkdir(parents=True, exist_ok=True)
    for name, text in (("pack.json", json.dumps(pack, ensure_ascii=False, indent=2)),
                       ("script.md", markdown)):
        temporary = where / f"{name}.tmp"
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(where / name)


def read_pack(clip_id: str) -> dict | None:
    try:
        return json.loads((root(clip_id) / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_markdown(clip_id: str) -> str | None:
    try:
        return (root(clip_id) / "script.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def discard(clip_id: str) -> None:
    try:
        shutil.rmtree(root(clip_id), ignore_errors=True)
    except ValueError:
        pass


# --- narration ----------------------------------------------------------------

def say_digest() -> str:
    from app import render
    try:
        return hashlib.sha256(render.SAY_PATH.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


async def prepare_narration(script: dict, locale: str, clip_id: str) -> dict:
    """Speak the Script once, keep the take, and report each Card's span.

    The same single edge-tts call the renderer makes, so the cut points the
    shot counts are planned from are the cut points the clip is rendered with.
    """
    from app import render
    work = root(clip_id) / "tts"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    audio, starts = await render._narration_track(script["cards"], work, locale)
    total = render.audio_seconds(audio)
    meta = {"audio": str(audio), "starts": starts, "total": total,
            "spans": spans(starts, total, render.TAIL_PAD), "say": say_digest()}
    (root(clip_id) / "narration.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def load_narration(clip_id: str) -> tuple[Path, list[float]] | None:
    """The saved take, unless `/say` changed since it was spoken."""
    try:
        meta = json.loads((root(clip_id) / "narration.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    audio = Path(meta["audio"])
    if meta.get("say") != say_digest() or not audio.is_file():
        return None
    return audio, list(meta["starts"])


# --- the export ----------------------------------------------------------------

def duration(path: Path) -> float:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float(done.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"อ่านความยาวไฟล์ไม่ได้: {done.stderr.strip()[-300:]}") from exc


def cut(export: Path, pending: list[int], shots: dict[int, int], clip_id: str,
        shot_len: float) -> dict[int, Path]:
    """One file per pending Card: its consecutive shots, silent, re-encoded.

    Re-encoded, not stream-copied: Flow exports carry a keyframe every 3s, so
    a copy would start each Card on the wrong frame.
    """
    made, offset = {}, 0
    for card in pending:
        count = shots[card]
        dest = segment_path(clip_id, card)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(".part.mp4")
        done = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{offset * shot_len:.3f}", "-i", str(export),
             "-t", f"{count * shot_len:.3f}", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(temporary)],
            capture_output=True, text=True, timeout=1800,
        )
        if done.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"หั่นคลิปไม่สำเร็จ: {done.stderr.strip()[-400:]}")
        temporary.replace(dest)
        made[card] = dest
        offset += count
    return made


# --- the inbox the Shop API writes into ----------------------------------------

def inbox_dir() -> Path:
    return Path(os.environ.get("STUDIO_INBOX", "/output/studio-inbox"))


def claim_inbox(tokens: set[str]) -> list[tuple[str, Path]]:
    """Exports for live pack versions, renamed so the next tick cannot take them twice."""
    inbox = inbox_dir()
    if not inbox.is_dir():
        return []
    taken = []
    for token in sorted(tokens):
        ready = inbox / f"{token}.mp4"
        if ready.is_file():
            claimed = inbox / f"{token}.mp4.taken"
            ready.replace(claimed)
            taken.append((token, claimed))
    return taken


def sweep_inbox(live: set[str], hours: float = 72) -> int:
    """Delete inbox files nobody will claim: past the wait, whatever their token."""
    inbox = inbox_dir()
    if not inbox.is_dir():
        return 0
    cutoff = time.time() - hours * 3600
    removed = 0
    for path in inbox.iterdir():
        token = path.name.split(".", 1)[0]
        if path.is_file() and path.stat().st_mtime < cutoff and (
                token not in live or path.name.endswith(".part")):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def version_for_message(wait: dict, message_id: int | None) -> str | None:
    if wait.get("kind") != "studio" or not message_id:
        return None
    for token, version in (wait.get("versions") or {}).items():
        # The pack message and its script.md document both take a reply.
        if message_id == version.get("message_id") or message_id in (version.get("message_ids") or []):
            return token
    return None
