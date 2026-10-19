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
# A speaking Card is one shot whose own audio is kept: the character says the
# narration on camera in Flow (docs/adr/0017). Measured on a real export
# (2026-10-19): Veo speaks Thai 15-25% slower than the edge-tts take. 8s shots
# held the 5.7s and 6.3s takes only just (speech ran to ~7.9s of 8) and the
# 7.1-7.9s takes ran into the cut, so 6.3s is the observed edge, not a margin.
# Longer Cards get Flow's 10s shot, scaled from that edge and not yet measured;
# longer than that is ✂️'s job.
SPEAK_LONG_SHOT = 10.0
VOICE_RATE = 24000  # the edge-tts take's own rate, so the concat needs no resample
SPEAK_MAX_TAKE = float(os.environ.get("SPEAK_MAX_TAKE_SECONDS", "6.3"))
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


def speak_seconds(span: float) -> float:
    """The Flow shot length for a speaking Card whose take runs `span` seconds."""
    return SHOT_SECONDS if span <= SPEAK_MAX_TAKE else SPEAK_LONG_SHOT


def speak_too_long(span: float) -> bool:
    return span > SPEAK_MAX_TAKE * SPEAK_LONG_SHOT / SHOT_SECONDS


def footage_seconds(shots: dict[int, int], seconds: dict[int, float] | None = None) -> dict[int, float]:
    """Seconds of export each Card owns: its shots times its shot length."""
    return {c: n * (seconds or {}).get(c, SHOT_SECONDS) for c, n in shots.items()}


def fits(duration: float, expected: float) -> bool:
    return abs(duration - expected) <= TOLERANCE + 1e-9


def lengths(pending: list[int], owned: dict[int, float], duration: float,
            even: bool) -> dict[int, float]:
    """Where to cut: each Card's seconds, stretched to the real length when cut evenly."""
    expected = sum(owned[c] for c in pending)
    scale = duration / expected if even and expected else 1.0
    return {c: owned[c] * scale for c in pending}


# --- files -------------------------------------------------------------------

def _base() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "studio"


def root(clip_id: str) -> Path:
    if not CLIP_ID.fullmatch(clip_id or ""):
        raise ValueError(f"clip id ไม่ถูกต้อง: {clip_id!r}")
    return _base() / clip_id


def segment_path(clip_id: str, card: int) -> Path:
    return root(clip_id) / "segments" / f"c{card:02d}.mp4"


def voice_path(clip_id: str, card: int) -> Path:
    """A speaking Card's own audio, cut from the export beside its video."""
    return root(clip_id) / "segments" / f"c{card:02d}.wav"


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


def cut(export: Path, pending: list[int], seconds: dict[int, float], clip_id: str,
        keep_voice: bool = False) -> dict[int, Path]:
    """One file per pending Card: its stretch of the export, silent, re-encoded.

    Re-encoded, not stream-copied: Flow exports carry a keyframe every 3s, so
    a copy would start each Card on the wrong frame. With `keep_voice` the
    Card's audio is cut too, as a separate file in the take's own format, for
    speaking_take() to splice in.
    """
    made, offset = {}, 0.0
    for card in pending:
        length = seconds[card]
        dest = segment_path(clip_id, card)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(".part.mp4")
        # -t on the input, not the output: it then bounds both outputs.
        args = ["ffmpeg", "-y", "-ss", f"{offset:.3f}", "-t", f"{length:.3f}", "-i", str(export),
                "-map", "0:v:0", "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(temporary)]
        voice = voice_path(clip_id, card)
        if keep_voice:
            args += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(VOICE_RATE),
                     "-c:a", "pcm_s16le", str(voice)]
        done = subprocess.run(args, capture_output=True, text=True, timeout=1800)
        if done.returncode != 0:
            temporary.unlink(missing_ok=True)
            voice.unlink(missing_ok=True)
            if keep_voice and "matches no streams" in done.stderr:
                raise RuntimeError("ไฟล์ไม่มีเสียง — export จาก Scenes ใหม่ (ต้องมีเสียงที่ตัวละครพูด)")
            raise RuntimeError(f"หั่นคลิปไม่สำเร็จ: {done.stderr.strip()[-400:]}")
        if not keep_voice:
            # A Card re-shot without speech must not keep last version's voice.
            voice.unlink(missing_ok=True)
        temporary.replace(dest)
        made[card] = dest
        offset += length
    return made


def speaking_take(clip_id: str, sources: list[str], audio: Path,
                  starts: list[float]) -> tuple[Path, list[float]]:
    """The saved take with every speaking Flow Card's slice swapped for its own voice.

    The Card's voice keeps its head, which is what keeps the lips in sync with
    the frames it was cut with; only its tail silence is trimmed, as tighten()
    trims the take's. Every piece is loudness-normalised so the switch between
    the character and the edge-tts voice does not also jump in level.
    """
    from app import render
    work = root(clip_id) / "speaking"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pcm = ["-ac", "1", "-ar", str(VOICE_RATE), "-c:a", "pcm_s16le"]
    pieces = []
    for i, start in enumerate(starts):
        raw, out = work / f"raw{i:02d}.wav", work / f"p{i:02d}.wav"
        voice = voice_path(clip_id, i)
        if sources[i] == "flow" and voice.is_file():
            args = ["ffmpeg", "-y", "-i", str(voice), "-af",
                    "areverse,silenceremove=start_periods=1:start_duration=0"
                    f":start_threshold={render.SILENCE_FLOOR}:start_silence={render.JOIN_SILENCE},"
                    "areverse"]
        else:
            args = ["ffmpeg", "-y", "-ss", f"{start:.3f}"]
            if i + 1 < len(starts):
                args += ["-to", f"{starts[i + 1]:.3f}"]
            args += ["-i", str(audio)]
        render._run([*args, *pcm, str(raw)])
        # A pass of its own: loudnorm in the same graph as areverse trips an
        # ffmpeg 7.1 assertion (`best_input >= 0`) on real Flow audio.
        render._run(["ffmpeg", "-y", "-i", str(raw), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11",
                     *pcm, str(out)])
        pieces.append(out)
    joined = render.concat_audio(pieces, work / "take.wav")
    new_starts, clock = [], 0.0
    for piece in pieces:
        new_starts.append(clock)
        clock += render.audio_seconds(piece)
    return joined, new_starts


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


def unclaim_inbox(tokens: set[str]) -> int:
    """Put back exports a restart caught mid-cut, so the next tick claims them again."""
    inbox = inbox_dir()
    if not inbox.is_dir():
        return 0
    restored = 0
    for token in sorted(tokens):
        claimed = inbox / f"{token}.mp4.taken"
        if claimed.is_file() and not (inbox / f"{token}.mp4").exists():
            claimed.replace(inbox / f"{token}.mp4")
            restored += 1
    return restored


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
