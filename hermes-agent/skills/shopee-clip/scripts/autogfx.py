#!/usr/bin/env python3
"""Draft fx.json and gfx.json from measurements, so no coordinate is reasoned out by hand.

On hatari-s14m1 (2026-11-16) the post stage ran its scripts for about 2 minutes and spent 81 model minutes
working out face boxes, punch centres, the hook card rect and sticker positions. This script measures them
with layout_probe (face detection + free-backdrop mask) and writes both plans. You then run the existing
gates on its output: `graphics_layer.py --check` and ONE vision look at a frame sheet of the render.

  # per RAW scene, before presenter_fx.py (scene-local seconds):
  autogfx.py fx shot1_a1.mp4 --out fx1.json --hook --product ref1.jpg      # scene 1: hook card + punch
  autogfx.py fx shot2_a1.mp4 --out fx2.json                                # later scenes: punch only

  # once, on post_presenter's out.mp4, before graphics_layer.py (final-clip seconds):
  autogfx.py gfx out.mp4 --report report.json --out gfx.json [--fx1 fx1.json]

Run with: uv run --with "opencv-python-headless<5" --with numpy python autogfx.py …
It prints what it wrote plus `skipped` reasons (no face found, no wall big enough for the hook card). A skipped
element is left out, never guessed. Edit the JSON afterwards for anything the product needs (a callout, a
headline); the numbers already in it stay.
"""
import argparse
import json
import os
import subprocess
import sys

W, H, S = 720, 1280, 4
HOOK_WINDOWS = (1.4, 2.0, 2.5, 3.0)     # successive windows from t=0; the last one that fits is the card's dur
HOOK_MIN_H, HOOK_MAX_H = 110, 300
PUNCH_LEN, PUNCH_ZOOM = 2.0, 1.12
CHUNK = 2.6                             # one avoid rect + at most one sticker per chunk of the final clip
STICKER = 56
# where a sticker centre may sit: under the pill band, over the sub band, off the platform's right rail
ZONE = (60, 290, 660, 660)
RAIL = (640, 560, W, H)
LOOKS = (("sparkle", "yellow", "twinkle"), ("sparkle", "mint", "twinkle"), ("star", "yellow", "bounce"),
         ("heart", "pink", "twinkle"))


# ---------------------------------------------------------------- pure layout (unit-tested, numpy only)
def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def hook_fit(rect, aspect):
    """An empty wall rect [x0,y0,x1,y1] -> the overlay card {x,y,h} that stays inside it, or None.
    presenter_fx draws the cutout on a canvas (aspect*h + 42) x (h + 42), starts it 40 px low and bobs it
    6 px, so the card needs h + 42 + 52 px of wall height."""
    if not rect:
        return None
    x0, x1 = max(rect[0], 5), min(rect[2], 715)
    y0, y1 = rect[1], rect[3]
    h = int(min(y1 - y0 - 94, (x1 - x0 - 42) / aspect, HOOK_MAX_H))
    if h < HOOK_MIN_H:
        return None
    top = y0 + (y1 - y0 - (h + 94)) / 2 + 6
    return {"x": int((x0 + x1) / 2), "y": int(top + (h + 42) / 2), "h": h}


def pick_hook(probes, aspect):
    """probes = layout_probe results for windows 0..1.4, 0..2.0, … -> (dur, card) of the LAST window whose
    wall still holds the card; the card is sized for that window, the tightest one."""
    best = None
    for p in probes:
        cards = [c for c in (hook_fit(p.get("empty_left"), aspect), hook_fit(p.get("empty_right"), aspect)) if c]
        if not cards:
            break
        best = (p["window"][1], max(cards, key=lambda c: c["h"]))
    return best


def punch_for(face, start, end):
    cx, cy = (face[0] + face[2]) // 2, (face[1] + face[3]) // 2
    return {"start": round(start, 2), "end": round(end, 2), "zoom": PUNCH_ZOOM, "cx": int(cx), "cy": int(cy), "ease": 0.12}


def chunks(t0, t1, size=CHUNK):
    """Split [t0, t1] into equal parts no longer than `size`."""
    n = max(1, int((t1 - t0) / size + 0.999))
    step = (t1 - t0) / n
    return [(round(t0 + i * step, 2), round(t0 + (i + 1) * step, 2)) for i in range(n)]


def scene_windows(report):
    """Final-clip windows to probe: every scene cut into chunks, 0.3 s clear of each seam and of the end."""
    scenes, end = report.get("scenes") or [], float(report.get("v_dur") or 0)
    starts = [float(s.get("global_start") or 0) for s in scenes] or [0.0]
    out = []
    for i, s0 in enumerate(starts):
        s1 = starts[i + 1] if i + 1 < len(starts) else end
        a, b = s0 + (0.3 if i else 0.1), s1 - (0.3 if i + 1 < len(starts) else 0.5)
        if b - a >= 0.8:
            out += [(i, c0, c1) for c0, c1 in chunks(a, b)]
    return out


def side_spot(face, y=None):
    """No free wall was measured: beside the face, on the side with more room."""
    if not face:
        return 600, 330
    left, right = face[0], W - face[2]
    x = face[2] + right // 2 if right >= left else face[0] - left // 2
    return int(min(max(x, ZONE[0] + 10), ZONE[2] - 10)), int(min(max(y or face[1] + 30, ZONE[1]), ZONE[3]))


def free_spot(busy, blocked, face, zone=ZONE, box=96):
    """Centre of a `box` px square that is free wall in every sampled frame, inside `zone`, clear of every
    rect in `blocked`; the one nearest the face. None when the mask has no such square (a real room, not a
    studio wall, reads as busy everywhere)."""
    if busy is None:
        return None
    n, best = box // S, None
    for cy in range(zone[1], zone[3] + 1, 20):
        for cx in range(zone[0], zone[2] + 1, 20):
            r = (cx - box // 2, cy - box // 2, cx + box // 2, cy + box // 2)
            if r[0] < 0 or r[1] < 0 or r[2] > W or r[3] > H or any(overlap(r, b) for b in blocked):
                continue
            if busy[r[1] // S:r[1] // S + n, r[0] // S:r[0] // S + n].any():
                continue
            fx, fy = ((face[0] + face[2]) / 2, (face[1] + face[3]) / 2) if face else (W / 2, 420)
            d = (cx - fx) ** 2 + (cy - fy) ** 2
            if best is None or d < best[0]:
                best = (d, cx, cy)
    return (best[1], best[2]) if best else None


def pad(rect, px):
    return [max(0, rect[0] - px), max(0, rect[1] - px), min(W, rect[2] + px), min(H, rect[3] + px)]


def plan_gfx(windows, hook=None):
    """windows = [{"scene", "t0", "t1", "face", "busy"}] in final-clip time -> (gfx plan, skipped notes).
    One avoid rect per window with a face (a window without one inherits its scene's last face), a sticker
    on up to 6 windows spread over the clip, and a bouncing arrow in the last window for the CTA."""
    avoid, stickers, skipped, last_face = [], [], [], {}
    for i, w in enumerate(windows):
        face = w.get("face") or last_face.get(w["scene"])
        if w.get("face"):
            last_face[w["scene"]] = w["face"]
        else:
            skipped.append(f"{w['t0']}-{w['t1']}s: no face found" + (" (reused the scene's last box)" if face else ""))
        w["_face"] = face
        if face:
            avoid.append({"name": f"face{i + 1}", "rect": pad(face, 10), "start": w["t0"], "end": w["t1"]})
    n = min(len(windows), max(3, min(6, round((windows[-1]["t1"] - windows[0]["t0"]) / 3.5)))) if windows else 0
    picked = sorted({round(k * (len(windows) - 1) / max(1, n - 1)) for k in range(n)}) if n else []
    spare = [i for i in range(len(windows)) if i not in picked]      # tried only while a picked window found no wall
    for i in picked + spare:
        if len(stickers) >= n:
            break
        j, w, face = len(stickers), windows[i], windows[i]["_face"]
        # the face, and the column under it: cream knitwear and a white product read as "wall" in the mask
        blocked = [RAIL] + ([pad(face, 30), [max(0, face[0] - 40), face[1], min(W, face[2] + 40), H]] if face else [])
        if hook and w["t0"] < hook["end"]:
            blocked.append(hook["rect"])
        last = i == len(windows) - 1 and len(windows) > 1
        zone = (ZONE[0], 480, ZONE[2], ZONE[3]) if last else ZONE
        if w.get("busy") is None:               # nothing was measured: beside the face
            spot = side_spot(face, 560 if last else None)
            if any(overlap((spot[0] - 28, spot[1] - 28, spot[0] + 28, spot[1] + 28), b) for b in blocked[1:]):
                spot = None
        else:                                   # measured: free smooth wall or nothing (never onto the product)
            spot = free_spot(w["busy"], blocked, face, zone) or free_spot(w["busy"], blocked, face, zone, box=64)
        if not spot and i in spare:
            continue
        if not spot:
            skipped.append(f"{w['t0']}-{w['t1']}s: no free wall for a {'CTA arrow' if last else 'sticker'} "
                           "(product or person fills the frame) — left out")
            continue
        start = round(w["t0"] + 0.3, 2)
        kind, color, anim = ("arrow", "yellow", "bounce") if last else LOOKS[j % len(LOOKS)]
        stickers.append({"kind": kind, "x": spot[0], "y": spot[1], "size": 64 if last else STICKER, "start": start,
                         "end": round(min(w["t1"], start + 2.0), 2), "color": color, "anim": anim})
    stickers.sort(key=lambda st: st["start"])
    for w in windows:
        w.pop("_face", None)
    if not stickers:
        skipped.append("NO sticker placed: `deliver` refuses an empty graphics plan — add one element by hand "
                       "(a callout on the product close-up, or a headline) and run --check")
    return {"stickers": stickers, "avoid": avoid, "auto_sfx": True, "sfx_gain": 0.35}, skipped


# ---------------------------------------------------------------- measuring (ffmpeg + OpenCV)
def duration(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def lp():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import layout_probe
    return layout_probe


def detail_mask(img, thr=5.0):
    """180x320 mask of textured cells in one frame. layout_probe's colour mask calls a white product or cream
    knitwear "wall"; a real wall is also smooth, so fine detail (a fan grille, knit, print) marks a cell busy."""
    import cv2
    import numpy as np
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap = cv2.blur(np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3)), (25, 25))
    return (cv2.resize(lap, (W // S, H // S), interpolation=cv2.INTER_AREA) > thr).astype(np.uint8)


def cmd_fx(a):
    probe, dur, fx, skipped, t = lp().probe, duration(a.video), {}, [], 0.6
    if a.hook:
        if not a.product:
            sys.exit("--hook needs --product <clean crop> (the card is the product cutout)")
        import cv2
        im = cv2.imread(a.product)
        aspect = im.shape[1] / im.shape[0]
        hit = pick_hook([probe(a.video, 0, e, 0.25, aspect) for e in HOOK_WINDOWS if e < dur - 0.5], aspect)
        if hit:
            fx["hook_card"] = {"image": a.product, "mode": "overlay", **hit[1], "dur": hit[0], "bg": a.bg}
            t = hit[0] + 0.3                    # a punch re-frames the video under a fixed sticker: keep them apart
        else:
            skipped.append("hook card: no empty wall holds a card of 110 px for 1.4 s — left out")
    end = min(t + PUNCH_LEN, dur - 0.5)
    if not a.no_punch and end - t >= 1.0:
        face = probe(a.video, t, end, 0.25)["face"]
        if not face:
            skipped.append(f"punch {t:.1f}-{end:.1f}s: no face found — left out")
        elif face[1] < 80 or face[3] - face[1] > 420:
            skipped.append(f"punch {t:.1f}-{end:.1f}s: she moves or leans into the camera there (face box {face}) — "
                           "left out; add one by hand on a steadier beat if the scene needs it")
        else:
            fx["punch"] = [punch_for(face, t, end)]
    return fx, skipped


def cmd_gfx(a):
    probe, grab = lp().probe, lp().frame
    with open(a.report, encoding="utf-8") as f:
        report = json.load(f)
    wins = []
    for scene, t0, t1 in scene_windows(report):
        p = probe(a.video, t0, t1, 0.4)
        busy = p["busy"]
        for t in (t0 + 0.3, (t0 + t1) / 2, t1 - 0.1):
            busy = busy | detail_mask(grab(a.video, t))
        wins.append({"scene": scene, "t0": t0, "t1": t1, "face": p["face"], "busy": busy})
    if not wins:
        sys.exit("report.json has no scene long enough to probe")
    hook = None
    if a.fx1 and os.path.exists(a.fx1):
        with open(a.fx1, encoding="utf-8") as f:
            hc = json.load(f).get("hook_card") or {}
        if hc.get("mode") == "overlay":
            hw = hc["h"] + 42                                    # square bound: wide enough for any product crop
            hook = {"end": float(hc["dur"]), "rect": [hc["x"] - hw // 2, hc["y"] - hw // 2 - 6, hc["x"] + hw // 2,
                                                      hc["y"] + hw // 2 + 46]}
    return plan_gfx(wins, hook)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("fx")
    s.add_argument("video")
    s.add_argument("--out", required=True)
    s.add_argument("--hook", action="store_true")
    s.add_argument("--product")
    s.add_argument("--bg", default="yellow")
    s.add_argument("--no-punch", action="store_true")
    s = sub.add_parser("gfx")
    s.add_argument("video")
    s.add_argument("--report", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--fx1")
    a = ap.parse_args(argv)
    for f in [a.video] + ([a.report] if a.cmd == "gfx" else [a.product] if a.product else []):
        if not os.path.exists(f):
            sys.exit(f"autogfx: no such file: {f}")
    plan, skipped = cmd_fx(a) if a.cmd == "fx" else cmd_gfx(a)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    nxt = ("presenter_fx.py <scene> " + a.out + " <scene_fx.mp4>" if a.cmd == "fx" else
           "graphics_layer.py out.mp4 " + a.out + " final.mp4 --report " + a.report + " --check, render, then ONE "
           "vision look at a frame sheet (each sticker's start + 0.3 s)")
    print(json.dumps({"wrote": a.out, "plan": plan, "skipped": skipped, "next": nxt}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
