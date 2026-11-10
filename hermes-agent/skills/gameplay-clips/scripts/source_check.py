#!/usr/bin/env python3
"""Gate for 🎬 product footage: is this video really the model being sold, and from the brand itself?

A brand video of the wrong model (VITURE Pro vs Pro 2 XR, a 10 kg vs 12 kg washer) sells the buyer a
different product. Run this on every candidate source BEFORE downloading or cutting it.

Usage:
  uv tool run yt-dlp --version >/dev/null   # (yt-dlp comes from `uv tool run`)
  python3 source_check.py <url> --model "Pro 2 XR" [--model "VITURE"] [--brand VITURE] [--search "ytsearch5:VITURE Pro 2 XR"]
  --model   tokens that must ALL appear in the title or description (case/space/hyphen-insensitive:
            "Pro 2 XR" matches "Pro2 XR" and "PRO-2-XR")
  --brand   the channel name (or uploader) must contain it -> official=true; otherwise official=false
            and the video is a third-party upload (reviewers, resellers) = do not use without Fix's OK
  --search  instead of one url, list the first results of a yt-dlp search with a verdict each

Prints JSON; exit 0 = model matches and official, 3 = mismatch or not official, 2 = error.
A pass is necessary, not sufficient: still vision-check frames for the model (badge, shape, ports)
against Fix's listing photos — titles can be generic ("VITURE XR glasses").
"""
import argparse
import json
import re
import subprocess
import sys


def norm(s):
    return re.sub(r"[^0-9a-z฀-๿]+", "", (s or "").lower())


def verdict(meta, models, brand=None):
    text = norm(f"{meta.get('title', '')} {meta.get('description', '')}")
    missing = [m for m in models if norm(m) not in text]
    who = f"{meta.get('channel') or ''} {meta.get('uploader') or ''}"
    official = bool(brand) and norm(brand) in norm(who)
    return {"ok": not missing and official, "title": meta.get("title"), "channel": meta.get("channel") or meta.get("uploader"),
            "url": meta.get("webpage_url"), "duration": meta.get("duration"), "missing_tokens": missing,
            "official": official}


def fetch(target, many=False):
    # metadata only: without --ignore-no-formats-error yt-dlp aborts on "Requested format is not available"
    # (no JS runtime in the container) before printing anything (seen 2026-11-10)
    cmd = ["uv", "tool", "run", "yt-dlp", "--skip-download", "--no-warnings", "--ignore-no-formats-error",
           "-J" if not many else "-j", target]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode and not r.stdout.strip():
        raise SystemExit(json.dumps({"ok": False, "error": r.stderr.strip()[-400:]}))
    if many:
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip().startswith("{")]
    return [json.loads(r.stdout)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--brand")
    ap.add_argument("--search")
    a = ap.parse_args()
    if not (a.url or a.search):
        ap.error("give a url or --search")
    try:
        metas = fetch(a.search, many=True) if a.search else fetch(a.url)
    except SystemExit as e:
        print(e.code)
        return 2
    out = [verdict(m, a.model, a.brand) for m in metas]
    print(json.dumps(out if a.search else out[0], ensure_ascii=False, indent=1))
    return 0 if all(v["ok"] for v in out) and out else 3


if __name__ == "__main__":
    sys.exit(main())
