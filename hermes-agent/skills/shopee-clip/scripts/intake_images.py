#!/usr/bin/env python3
"""Gather EVERY image Fix sent with a clip order and build ONE labelled contact sheet.

Telegram delivers a multi-photo send as separate messages, each in its own
native-inputs/<hash>/ folder, so the order turn usually shows only the first
photo. This script collects all sibling folders whose mtime sits within
--window seconds of the anchor image, copies them into the work dir under
stable names (img1.jpg, img2.jpg, ...) and tiles them into sheet.jpg, so ONE
vision call analyses the whole set before any storyboard is written.

Usage:
  uv run --with pillow python intake_images.py <anchor_image> <workdir> [--window 90] [--wait 20]

--wait: seconds to sleep first, so photos still uploading land before the scan.
Prints one JSON line: {"anchor":..., "images":[{"n":1,"src":...,"dst":...,"mtime":...,"wh":[w,h]}], "sheet":...}

Spec numbers (keem-herm-loud-800a 2026-11-27: listing "800A", photo printed "300A"): when the job's product title
(clipjob intake --product) names a number + unit, the copied photos are OCR'd by speccheck.py (~2 s a photo) and a
conflict is printed as "spec_conflict" + `next` right here, BEFORE the photo gate and the board. The result is
cached in <workdir>/spec.json for clipjob.py (board / pack / reserve / deliver gate on it).
"""
import argparse, glob, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.environ.get("CLIPJOB_DIR", "/opt/data/clips/jobs")

ROOT = "/opt/data/cache/documents/native-inputs"
EXTS = (".jpg", ".jpeg", ".png", ".webp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("anchor")
    ap.add_argument("workdir")
    ap.add_argument("--window", type=float, default=90.0)
    ap.add_argument("--wait", type=float, default=20.0)
    a = ap.parse_args()
    if a.wait > 0:
        time.sleep(a.wait)
    t0 = os.path.getmtime(a.anchor)
    files = []
    for d in glob.glob(os.path.join(ROOT, "*")):
        for f in glob.glob(os.path.join(d, "*")):
            if f.lower().endswith(EXTS):
                m = os.path.getmtime(f)
                if abs(m - t0) <= a.window:
                    files.append((m, f))
    files.sort()
    os.makedirs(a.workdir, exist_ok=True)
    from PIL import Image, ImageDraw
    out, tiles = [], []
    for i, (m, f) in enumerate(files, 1):
        ext = os.path.splitext(f)[1].lower()
        dst = os.path.join(a.workdir, f"img{i}{ext}")
        shutil.copy2(f, dst)
        im = Image.open(f).convert("RGB")
        out.append({"n": i, "src": f, "dst": dst, "mtime": time.strftime("%H:%M:%S", time.localtime(m)),
                    "wh": list(im.size), "anchor": os.path.samefile(f, a.anchor)})
        im.thumbnail((480, 480))
        tile = Image.new("RGB", (480, 520), "white")
        tile.paste(im, ((480 - im.width) // 2, 40))
        ImageDraw.Draw(tile).text((10, 10), f"IMAGE {i}", fill=(220, 0, 0))
        tiles.append(tile)
    sheet = None
    if tiles:
        cols = min(3, len(tiles))
        rows = (len(tiles) + cols - 1) // cols
        S = Image.new("RGB", (cols * 480, rows * 520), (230, 230, 230))
        for k, t in enumerate(tiles):
            S.paste(t, ((k % cols) * 480, (k // cols) * 520))
        sheet = os.path.join(a.workdir, "intake_sheet.jpg")
        S.save(sheet, quality=90)
    res = {"anchor": a.anchor, "count": len(out), "images": out, "sheet": sheet}
    res.update(spec(a.workdir, [o["dst"] for o in out]))
    print(json.dumps(res, ensure_ascii=False))


def spec(workdir, imgs):
    """speccheck over the copied photos when the job's title names a spec number -> {} or {"spec_conflict", "next"}."""
    sys.path.insert(0, HERE)
    import speccheck
    jf = os.path.join(JOBS, os.path.basename(os.path.normpath(workdir)) + ".json")
    try:
        with open(jf, encoding="utf-8") as f:
            title = json.load(f).get("product") or ""
    except (OSError, ValueError):
        return {}
    if not imgs or not speccheck.spec_tokens(title):
        return {}
    r = subprocess.run(["uv", "run", "-q", "--with", "rapidocr-onnxruntime", "--with", "numpy", "--with", "pillow",
                        "python", os.path.join(HERE, "speccheck.py"), "scan", "--title", title, *imgs],
                       capture_output=True, text=True)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"spec_scan": f"failed (rc {r.returncode}): {(r.stdout + r.stderr)[-200:]}"}
    got["title_text"] = title
    with open(os.path.join(workdir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(got, f, ensure_ascii=False, indent=1)
    if not got.get("conflicts"):
        return {}
    ban = speccheck.banned(got["conflicts"])
    return {"spec_conflict": got["conflicts"],
            "next": (f"SPEC CONFLICT — {speccheck.describe(got['conflicts'])}. Write the board WITHOUT "
                     f"{', '.join(ban)} (VO, pills, cover) and put the question to Fix as one button per number in "
                     "the approval clarify; his pick = clipjob.py spec <job> --ok <token>. pack / reserve / deliver "
                     "refuse those numbers until then")}


if __name__ == "__main__":
    main()
