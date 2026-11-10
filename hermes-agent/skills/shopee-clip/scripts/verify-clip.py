#!/usr/bin/env python3
"""Final verification for a downloaded/stitched Flow clip. One command, one verdict.

Usage:
    python3 verify-clip.py [path/to/clip.mp4]

Without a path it picks the NEWEST .mp4 in /opt/data/Downloads and
/opt/data/home/Downloads (Flow lands the file in either, never predictable).

Checks, in order:
  1. sha256 of the file, compared against EVERY .mp4 in BOTH download dirs
     (a byte-identical hash means you re-fetched an earlier clip, not a new one)
  2. ffprobe: h264 720x1280 + aac, duration > 1 s
  3. Reel-readiness (Facebook Reels gate): video pix_fmt yuv420p, profile NOT
     4:4:4 (an ffmpeg xfade stitch without explicit -pix_fmt/-profile ships
     'High 4:4:4 Predictive' + yuv444p, which the Reels editor refuses with
     'Cannot play video'), level <= 42, stereo audio at 44.1/48 kHz, and moov
     before mdat (faststart). A failure here = re-encode with
     -pix_fmt yuv420p -profile:v high -level 4.0 + bt709 tags, never send.
  4. copy to /opt/data/home/Downloads (single canonical send location)

Exit 0 + JSON verdict on success; exit 1 with the reason on any failure.
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

DIRS = ["/opt/data/Downloads", "/opt/data/home/Downloads"]
CANONICAL = "/opt/data/home/Downloads"
HEAD = 400000  # bytes scanned for the moov-before-mdat faststart test


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def faststart(path):
    """True when moov sits before mdat (upload-friendly)."""
    with open(path, "rb") as f:
        head = f.read(HEAD)
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    if moov < 0:
        return False, "no moov atom in first %d bytes" % HEAD
    if mdat >= 0 and moov > mdat:
        return False, "moov after mdat (not faststart)"
    return True, "faststart"


def newest_mp4():
    cands = []
    for d in DIRS:
        cands += glob.glob(os.path.join(d, "*.mp4"))
    if not cands:
        sys.exit(json.dumps({"ok": False, "reason": "no .mp4 in " + ", ".join(DIRS)}))
    return max(cands, key=os.path.getmtime)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else newest_mp4()
    if not os.path.isfile(src):
        sys.exit(json.dumps({"ok": False, "reason": "not a file: " + src}))

    digest = sha256(src)

    # 1. uniqueness across both download dirs. The canonical copy in
    #    CANONICAL with the SAME basename is expected (it is this clip
    #    already placed for sending), so only a different file counts.
    dupes = []
    for pattern in (os.path.join(DIRS[0], "*.mp4"), os.path.join(DIRS[1], "*.mp4")):
        for p in glob.glob(pattern):
            if os.path.abspath(p) == os.path.abspath(src):
                continue
            if sha256(p) != digest:
                continue
            if os.path.basename(p) == os.path.basename(src):
                continue  # the canonical copy of this very file
            dupes.append(p)
    if dupes:
        sys.exit(json.dumps({
            "ok": False,
            "reason": "byte-identical to an earlier clip",
            "sha256": digest,
            "dupes": dupes,
            "src": src,
        }))

    # 2. ffprobe
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,profile,pix_fmt,level,width,height,"
             "sample_rate,channels:format=duration",
             "-of", "json", src],
            capture_output=True, text=True, check=True,
        )
        info = json.loads(out.stdout)
    except Exception as e:  # ffprobe missing / parse failure
        sys.exit(json.dumps({"ok": False, "reason": "ffprobe failed: " + str(e), "src": src}))

    streams = {s.get("codec_type"): s for s in info.get("streams", [])}
    video, audio = streams.get("video"), streams.get("audio")
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    problems = []
    if not video or video.get("codec_name") != "h264":
        problems.append("video codec not h264")
    if not video or (video.get("width"), video.get("height")) != (720, 1280):
        problems.append("not 720x1280 (got %sx%s)" % (
            video.get("width") if video else "?", video.get("height") if video else "?"))
    if not audio or audio.get("codec_name") != "aac":
        problems.append("audio codec not aac")
    if duration <= 1.0:
        problems.append("duration %.2fs looks empty" % duration)

    # 3. Reel-readiness (the Facebook gate — a yuv444p stitch plays nowhere)
    if video:
        pix = video.get("pix_fmt") or ""
        prof = video.get("profile") or ""
        if pix != "yuv420p":
            problems.append("pix_fmt %s not yuv420p (Reels rejects it)" % (pix or "?"))
        if "4:4:4" in prof:
            problems.append("profile '%s' is 4:4:4 — re-encode with "
                            "-pix_fmt yuv420p -profile:v high -level 4.0" % prof)
        try:
            if int(video.get("level") or 0) > 42:
                problems.append("h264 level %s above 4.2" % video.get("level"))
        except (TypeError, ValueError):
            problems.append("h264 level unreadable")
        if audio:
            try:
                if int(audio.get("channels") or 0) != 2:
                    problems.append("audio not stereo")
                if int(audio.get("sample_rate") or 0) not in (44100, 48000):
                    problems.append("audio sample_rate %s not 44.1/48 kHz"
                                    % audio.get("sample_rate"))
            except (TypeError, ValueError):
                problems.append("audio format unreadable")
    ok_fast, fast_reason = faststart(src)
    if not ok_fast:
        problems.append(fast_reason)

    if problems:
        sys.exit(json.dumps({"ok": False, "reason": "; ".join(problems),
                             "src": src, "probe": info}, ensure_ascii=False))

    # 4. canonical copy
    dst = os.path.join(CANONICAL, os.path.basename(src))
    if os.path.abspath(dst) != os.path.abspath(src):
        if not os.path.exists(dst) or sha256(dst) != digest:
            shutil.copy(src, dst)

    print(json.dumps({
        "ok": True,
        "src": src,
        "sent_from": dst,
        "sha256": digest,
        "size": os.path.getsize(src),
        "width": video["width"],
        "height": video["height"],
        "video": video["codec_name"],
        "profile": video.get("profile"),
        "pix_fmt": video.get("pix_fmt"),
        "level": video.get("level"),
        "faststart": fast_reason,
        "audio": audio["codec_name"],
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
        "duration_s": round(duration, 3),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
