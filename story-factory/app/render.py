"""Building the Story: one Backdrop, one waveform, one encode.

Measured on the NAS 2026-09-14, 60s of audio, `-threads 3`:

    preset      wall    peak RSS   size
    ultrafast   17.9s     249 MB   22.7 MB
    superfast   29.9s     369 MB   30.7 MB
    veryfast    46.6s     409 MB   11.9 MB   <- default

and at 300s, veryfast/crf20: 184.2s wall, 380 MB RSS, 59.1 MB, duration exactly
300.000. That is 0.61x realtime and slightly better than linear, so a 40-minute
Story is about 25 minutes of wall clock and ~470 MB.

Two things fell out of those numbers:

  * `showwaves` is free (1.0s and 61 MB for a minute of audio). All the cost is
    x264. Rendering the waveform to its own file first and overlaying it after
    therefore saves nothing — measured at 48.7s against 46.5s, for 2.7x the
    memory. It is one pass.
  * `-tune stillimage` does not apply. The waveform moves, so every frame is a
    new frame; it cost 1.5s and 1.4 MB for nothing.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from . import config

#: 1920x1080 with the waveform strip across the lower third.
WAVEFORM_SIZE = "800x200"
WAVEFORM_X = "(W-w)/2"
WAVEFORM_Y = "H*3/4"


def probe_duration(path: Path) -> float:
    """Read a file's real duration. Every duration in this stack is measured
    from a file; none is predicted from what an API said it would be."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


async def run(program: str, *args: str) -> None:
    """Run a media tool as an asyncio subprocess.

    Not `subprocess.run` and not `asyncio.to_thread`: neither can be stopped
    once started, and a 25-minute encode that cannot be stopped means `/cancel`
    is a lie for 25 minutes. Cancelling the awaiting task kills the process.
    Also keeps the poll loop alive — a blocking call here froze `getUpdates`
    for the length of the encode.
    """
    proc = await asyncio.create_subprocess_exec(
        program, *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode:
        tail = stderr.decode(errors="replace")[-800:]
        raise RuntimeError(f"{program} exited {proc.returncode}: {tail}")


async def ffmpeg(*args: str) -> None:
    await run("ffmpeg", "-y", *args)


async def concat(parts: list[Path], dest: Path) -> Path:
    """Join same-format audio files without re-encoding."""
    listing = dest.with_suffix(".txt")
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    await ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dest))
    return dest


async def ping_pong(clip: Path, dest: Path) -> Path:
    """Play a Flow clip forwards then backwards, so the loop has no visible seam.

    `reverse` buffers every frame of the doubled clip in memory — about 3.1 MB a
    frame at 1080p24, so 10 seconds already crowds `mem_limit: 2g`. Hence
    BACKDROP_MAX_SECONDS. Measured at 9.0s and 730 MB for a 6s clip, once per
    Story, which is why this writes to a file instead of living inside the main
    filter graph where it would hold that memory for the whole encode.
    """
    length = probe_duration(clip)
    limit = config.backdrop_max_seconds()
    if length > limit:
        raise ValueError(
            f"Backdrop clip is {length:.1f}s; the reverse pass holds every frame "
            f"in memory and the cap is {limit:.0f}s",
        )

    await ffmpeg(
        "-i", str(clip),
        "-filter_complex",
        "[0:v]split[fwd][rev];[rev]reverse[back];[fwd][back]concat=n=2:v=1:a=0[out]",
        "-map", "[out]",
        "-an",
        "-c:v", "libx264",
        "-preset", config.render_preset(),
        "-crf", str(config.render_crf()),
        "-threads", str(config.render_threads()),
        str(dest),
    )
    return dest


#: Backdrops that are one picture rather than a clip. A still needs `-loop 1`
#: and a framerate; `-stream_loop -1` on an image input yields a single frame
#: and a one-frame video, which `build()` only catches at the very end after the
#: whole Story has been written and voiced.
STILL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _input_flags(backdrop: Path) -> list[str]:
    if backdrop.suffix.lower() in STILL_SUFFIXES:
        return ["-loop", "1", "-framerate", "24", "-i", str(backdrop)]
    # A clip is a few seconds long and the Story is forty minutes, so it loops.
    return ["-stream_loop", "-1", "-i", str(backdrop)]


def build_command(backdrop: Path, audio: Path, dest: Path) -> list[str]:
    """The single encode. Split out from `build` so a test can read it without
    spending 25 minutes of CPU."""
    return [
        "ffmpeg", "-y",
        # `-shortest` ends the video with the narration — verified by ffprobe
        # rather than assumed, because a wrong pairing here truncates the Story
        # to the length of the Backdrop without erroring.
        *_input_flags(backdrop),
        "-i", str(audio),
        "-filter_complex",
        (
            f"[1:a]showwaves=s={WAVEFORM_SIZE}:mode=cline:colors=white@0.8[wave];"
            f"[0:v][wave]overlay={WAVEFORM_X}:{WAVEFORM_Y}:format=auto[v]"
        ),
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264",
        "-preset", config.render_preset(),
        "-crf", str(config.render_crf()),
        "-pix_fmt", "yuv420p",
        # DSM's kernel has no CFS bandwidth control, so `cpus:` in compose is a
        # no-op. This is the only cap that takes effect.
        "-threads", str(config.render_threads()),
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(dest),
    ]


async def build(backdrop: Path, audio: Path, dest: Path) -> Path:
    await run(*build_command(backdrop, audio, dest))

    # Verify rather than trust. `-shortest` with a looping input is exactly the
    # combination that silently produces a file a fifth of the intended length.
    want = probe_duration(audio)
    got = probe_duration(dest)
    if abs(got - want) > 1.0:
        raise RuntimeError(
            f"render is {got:.1f}s but the narration is {want:.1f}s — "
            f"the Backdrop loop or -shortest is wrong",
        )
    return dest
