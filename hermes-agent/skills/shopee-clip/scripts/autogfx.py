#!/usr/bin/env python3
"""Draft fx.json and gfx.json from measurements, so no coordinate is reasoned out by hand.

On hatari-s14m1 (2026-11-16) the post stage ran its scripts for about 2 minutes and spent 81 model minutes
working out face boxes, punch centres, the hook card rect and sticker positions. This script measures them
with layout_probe (face detection + free-backdrop mask) and writes both plans. You then run the existing
gates on its output: `graphics_layer.py --check` and ONE vision look at a frame sheet of the render.

  # per RAW scene, before presenter_fx.py (scene-local seconds):
  autogfx.py fx shot1_a1.mp4 --out fx1.json --hook --product ref1.jpg      # scene 1: hook card + punch
  autogfx.py fx shot2_a1.mp4 --out fx2.json                                # later scenes: punch only
  # the board named the beats: one punch per --punch-at (replaces the automatic one); `:face`, `:product`
  # or `:auto` (default: a steady face, else the product found by the ref's colour, else by detail)
  autogfx.py fx shot1_a1.mp4 --out fx1.json --product ref1.jpg --punch-at 0.6-2.6:face --punch-at 4.4-6.4:product

  # once, on post_presenter's out.mp4, before graphics_layer.py (final-clip seconds):
  autogfx.py gfx out.mp4 --report report.json --out gfx.json [--fx1 fx1.json] \
      [--product-sticker ref1.jpg [--sticker-at 11.1-20.2]] [--headline "No Phone@8.5-10.4"]
  # --product-sticker: the board's product cut-out as an `image_stickers` entry, in the window of
  #   --sticker-at (default: the last scene) where it fits biggest — on free wall, else beside her face;
  # --headline TEXT@T0-T1: a headline (e.g. a pill post_presenter dropped off her face) at a measured y.
  # report.json `headlines` (the CTA post_presenter could not fit beside her head) are added the same way.
  # --product REF (default: the --product-sticker image): the product she holds is located in every window by
  #   the ref's hue, and neither the cut-out nor a headline is put on it (decker-cordless-drill 2026-11-27: the
  #   cut-out sat on the drill in her hand and "2 BATTERIES" across its body — the old saturation-110 colour box
  #   found only a few teal accents of a muted drill).

  # product boxes at given times (post_presenter keeps subtitles off them):
  autogfx.py boxes scene.mp4 --product ref1.jpg --at 0.4,1.2,2.0

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


# ---------------------------------------------------------------- board-named beats and elements
SUB_TOP, PILL_BOTTOM = 700, 262          # graphics_layer SUB_BAND top / PILL_BAND bottom
IMG_PAD = 42                             # image sticker border + shadow (graphics_layer: w_est + 42, h + 42)
# only strongly saturated pixels count as product colour: at 70 blonde hair, skin and a cream sweater matched an
# orange strap (huawei-watchfit5: the "product" landed on her hair, 300 px off the watch)
COLOUR_SAT = 110


def parse_span(text, default_on=None):
    """'4.4-6.4' / '4.4-6.4:product' -> (4.4, 6.4, on)."""
    span, _, on = text.partition(":")
    a, _, b = span.partition("-")
    t0, t1 = float(a), float(b)
    if t1 <= t0:
        raise ValueError(f"bad window {text!r}: end must be after start")
    return t0, t1, (on or default_on)


def spread(points):
    """Median point of [(x, y)] and the largest distance of any point from it."""
    xs, ys = sorted(p[0] for p in points), sorted(p[1] for p in points)
    mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
    return (mx, my), max(((p[0] - mx) ** 2 + (p[1] - my) ** 2) ** 0.5 for p in points)


def image_rect(cx, cy, h, aspect):
    w = aspect * h + IMG_PAD
    return (cx - w / 2, cy - (h + IMG_PAD) / 2, cx + w / 2, cy + (h + IMG_PAD) / 2)


def plausible_face(face):
    """Haar reads cable-knit as a face: a box whose top sits in the lower half of the frame, or that is taller
    than a close-up face, is not one to place a sticker beside (huawei-watchfit5: a 'face' at y 992 put the
    cut-out over her mouth)."""
    return bool(face) and face[1] < 560 and 90 <= face[3] - face[1] <= 620 and 80 <= face[2] - face[0] <= 560


def fit_image(busy, face, aspect, blocked, h_max=220, h_min=110):
    """Biggest product cut-out (h, cx, cy, how) for one window. First on free wall (every busy-mask cell
    under it empty); else beside her face, ignoring the wall mask (a real room reads busy everywhere) but
    never on the face, the body column under it, the sub band, the pill band or the right rail."""
    tries = []
    if busy is not None:
        tries.append(("free wall", busy, blocked))
    if plausible_face(face):
        body = [max(0, face[0] - 20), face[1], min(W, face[2] + 20), H]
        tries.append(("beside face", None, blocked + [pad(face, 20), body]))
    for how, mask, blk in tries:
        for h in range(h_max, h_min - 1, -10):
            hh, w = h + IMG_PAD, aspect * h + IMG_PAD
            best = None
            for cy in range(int(PILL_BOTTOM + hh / 2), int(SUB_TOP - hh / 2) + 1, 10):
                for cx in range(int(5 + w / 2), int(W - 5 - w / 2) + 1, 10):
                    r = image_rect(cx, cy, h, aspect)
                    if any(overlap(r, b) for b in blk):
                        continue
                    if mask is not None and mask[int(r[1]) // S:int(r[3] + S - 1) // S,
                                                 int(r[0]) // S:int(r[2] + S - 1) // S].any():
                        continue
                    fx, fy = ((face[0] + face[2]) / 2, (face[1] + face[3]) / 2) if face else (W / 2, 420)
                    d = (cx - fx) ** 2 + (cy - fy) ** 2
                    if best is None or d < best[0]:
                        best = (d, cx, cy)
            if best:
                return h, best[1], best[2], how
    return None


def place_product_sticker(windows, image, aspect, t0, t1, hook=None):
    """windows (final-clip chunks with face + busy) inside [t0, t1] -> (image_stickers entry, note)."""
    best = None
    for w in windows:
        if w["t0"] < t0 - 0.05 or w["t1"] > t1 + 0.05:
            continue
        blocked = [RAIL] + list(w.get("product") or []) + ([hook["rect"]] if hook and w["t0"] < hook["end"] else [])
        fit = fit_image(w.get("busy"), w.get("face"), aspect, blocked)
        # free wall beats beside-face, then the bigger cut-out, then the later window (the CTA beat)
        if fit and (best is None or (fit[3] == "free wall", fit[0], w["t0"]) > (best[1][3] == "free wall", best[1][0], best[0]["t0"])):
            best = (w, fit)
    if not best:
        return None, (f"product sticker {t0}-{t1}s: no window holds a {110} px cut-out beside her face or on free "
                      "wall — left out (put it in a later beat, or drop the board's promise and say so)")
    w, (h, cx, cy, how) = best
    entry = {"image": image, "x": cx, "y": cy, "h": h, "w_est": int(round(aspect * h)), "rot": -6,
             "start": round(w["t0"] + 0.2, 2), "end": round(w["t1"], 2)}
    return entry, f"product sticker {entry['start']}-{entry['end']}s h {h} ({how})"


def place_headline(text, t0, t1, faces, pills, subs, rect_fn, taken=(), products=(), sub_rects=None):
    """faces = [(t0, t1, rect)], pills/subs = report rows, taken = [(t0, t1, rect)] of elements already placed,
    products = [(t0, t1, rect)] of the product she holds, sub_rects = report `sub_rects` (one per sub row; the
    fixed band when absent) -> (headline entry, note). Tries sizes 58/52/46 and every y from the top of the safe
    box down; the first rect that is inside the safe box and clear of every face, of the product, of the pill
    band while a pill shows, of each showing sub and of the taken rects wins."""
    live = lambda rows: [r for r in rows if r[0] < t1 and t0 < r[1]]
    blk = [f[2] for f in live(faces)] + [x[2] for x in live(list(taken))] + [x[2] for x in live(list(products))]
    if live(pills):
        blk.append((0, 186, W, PILL_BOTTOM))
    rects = sub_rects if sub_rects and len(sub_rects) == len(subs) else [(0, SUB_TOP, W, 835)] * len(subs)
    blk += [r for s, r in zip(subs, rects) if s[0] < t1 and t0 < s[1]]
    for size in (58, 52, 46):
        for y in range(192, 832, 10):
            r = rect_fn(text, size, y)
            if r[0] < 80 or r[2] > 592 or r[1] < 192 or r[3] > 832:
                continue
            if not any(overlap(r, b) for b in blk):
                return ({"text": text, "start": round(t0, 2), "end": round(t1, 2), "y": y, "style": "pop",
                         "size": size}, f"headline '{text}' {t0}-{t1}s y {y} size {size}")
    return None, (f"headline '{text}' {t0}-{t1}s: no y clear of her face, the product and the pill/sub bands — "
                  "left out (a shorter text, or another beat)")


# ---------------------------------------------------------------- product box (OpenCV): hue of the ref
SKIN_HUE = 22            # OpenCV hue <= this or >= 180 - 10: red / orange / yellow, the hues of skin, hair, a vest
HUE_TOL, HUE_TOL_SKIN = 12, 6
HUE_SAT, HUE_SAT_SKIN = 45, 140    # a muted teal drill reads sat 60-100 on video; skin-like hues need a vivid colour
HUE_MIN_SHARE = 0.06     # share of the ref's foreground in that colour: below it the product is black / white / grey
BOX_GROW, BOX_KEEP, BOX_GAP, BOX_PAD = 25, 0.15, 220, 0.15


def skin_like(hue):
    return hue <= SKIN_HUE or hue >= 170


def hue_model(img):
    """Ref crop -> {"hue", "sat", "tol", "share"} of its dominant vivid colour, or None (not colourful enough)."""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    edge = np.concatenate([img[:4].reshape(-1, 3), img[-4:].reshape(-1, 3), img[:, :4].reshape(-1, 3),
                           img[:, -4:].reshape(-1, 3)]).astype(int)
    fg = np.sqrt(((img.astype(int) - np.median(edge, axis=0)) ** 2).sum(axis=2)) > 40
    vivid = fg & (hsv[..., 1] > 80) & (hsv[..., 2] > 50)
    share = float(vivid.sum()) / max(1, int(fg.sum()))
    if share < HUE_MIN_SHARE or vivid.sum() < 300:
        return None
    raw = np.bincount(hsv[..., 0][vivid], minlength=180).astype(float)
    smooth = np.convolve(np.r_[raw[-6:], raw, raw[:6]], np.ones(13), "valid")      # circular, +-6
    s = int(np.argmax(smooth))
    near = [(s + d) % 180 for d in range(-6, 7)]
    hue = max(near, key=lambda h: raw[h])               # the busiest hue inside the busiest +-6 band
    skin = skin_like(hue)
    return {"hue": hue, "sat": HUE_SAT_SKIN if skin else HUE_SAT, "tol": HUE_TOL_SKIN if skin else HUE_TOL,
            "share": round(share, 2)}


def product_box(img, md):
    """Box [x0, y0, x1, y1] around the product in one frame: every patch of the ref's hue, grown to join its
    parts, the biggest cluster plus the parts within BOX_GAP px of it, padded by BOX_PAD of its size for the
    black / chrome parts the hue cannot see. None when the frame has none of that colour."""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    d = np.abs(((hsv[..., 0].astype(int) - md["hue"] + 90) % 180) - 90)
    m = ((d <= md["tol"]) & (hsv[..., 1] > md["sat"]) & (hsv[..., 2] > 35)).astype(np.uint8) * 255
    m = cv2.dilate(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), np.ones((BOX_GROW, BOX_GROW), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    comps = [st[k] for k in range(1, n) if st[k, 4] >= 0.002 * W * H]
    if not comps:
        return None
    big = max(comps, key=lambda s: s[4])
    bx = [int(big[0]), int(big[1]), int(big[0] + big[2]), int(big[1] + big[3])]
    for s in sorted(comps, key=lambda s: -s[4]):
        if s[4] < BOX_KEEP * big[4]:
            continue
        r = [int(s[0]), int(s[1]), int(s[0] + s[2]), int(s[1] + s[3])]
        if max(0, r[0] - bx[2], bx[0] - r[2], r[1] - bx[3], bx[1] - r[3]) <= BOX_GAP:
            bx = [min(bx[0], r[0]), min(bx[1], r[1]), max(bx[2], r[2]), max(bx[3], r[3])]
    px, py = int((bx[2] - bx[0]) * BOX_PAD) + 10, int((bx[3] - bx[1]) * BOX_PAD) + 10
    return [max(0, bx[0] - px), max(0, bx[1] - py), min(W, bx[2] + px), min(H, bx[3] + py)]


def cmd_boxes(a):
    """`boxes`: the product box at each --at time (scene-local s) as JSON, for post_presenter's subtitles."""
    import cv2
    md = hue_model(cv2.imread(a.product))
    if md is None:
        return {"model": None, "boxes": [], "why": "the ref is black / white / grey: no hue to find it by"}
    grab = lp().frame
    return {"model": md, "boxes": [[t, product_box(grab(a.video, t), md)] for t in (float(x) for x in a.at.split(",") if x)]}


# ---------------------------------------------------------------- product locator (OpenCV)
def ref_colour_model(img):
    """Product crop -> HS histogram of its colourful foreground, or None when the product is not colourful
    enough to be found by colour (white / black / grey: the locator centres on fine detail instead)."""
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    edge = np.concatenate([img[:4].reshape(-1, 3), img[-4:].reshape(-1, 3), img[:, :4].reshape(-1, 3),
                           img[:, -4:].reshape(-1, 3)]).astype(int)
    fg = np.sqrt(((img.astype(int) - np.median(edge, axis=0)) ** 2).sum(axis=2)) > 40
    col = fg & (hsv[..., 1] > COLOUR_SAT) & (hsv[..., 2] > 50)
    if col.sum() < max(200, 0.12 * fg.sum()):
        return None
    hist = cv2.calcHist([hsv], [0, 1], col.astype(np.uint8) * 255, [30, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 255, cv2.NORM_MINMAX)
    return hist


def colour_centre(img, hist):
    import cv2
    import numpy as np
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bp = cv2.calcBackProject([hsv], [0, 1], hist, [0, 180, 0, 256], 1)
    bp[hsv[..., 1] <= COLOUR_SAT] = 0
    m = cv2.threshold(cv2.GaussianBlur(bp, (9, 9), 0), 60, 255, cv2.THRESH_BINARY)[1]
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, cent = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return None if stats[k, cv2.CC_STAT_AREA] < 0.0005 * W * H else (int(cent[k][0]), int(cent[k][1]))


def detail_centre(img, face=None):
    import cv2
    import numpy as np
    dens = cv2.blur(cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 80, 160).astype(np.float32), (121, 121))
    if face:
        dens[max(0, face[1]):face[3], max(0, face[0]):face[2]] = 0
    y, x = np.unravel_index(int(np.argmax(dens)), dens.shape)
    return int(x), int(y)


def product_centre(video, t0, t1, hist, face=None, n=7):
    """(cx, cy, how) of the product across [t0, t1], or (None, reason)."""
    grab = lp().frame
    ts = [t0 + (t1 - t0) * (i + 0.5) / n for i in range(n)]
    how = "colour" if hist is not None else "detail"
    pts = [p for p in ((colour_centre(grab(video, t), hist) if hist is not None else detail_centre(grab(video, t), face))
                       for t in ts) if p]
    if len(pts) < (n + 1) // 2:
        return None, f"the ref's colour was found in {len(pts)}/{n} frames"
    (cx, cy), far = spread(pts)
    if far > 140:
        return None, f"the product moves {int(far)} px across the beat ({how})"
    return (cx, cy, how), None


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
    if a.punch_at:
        punches, skipped = board_punches(a, probe, dur, t if fx.get("hook_card") else 0.0, skipped)
        if punches:
            fx["punch"] = punches
        return fx, skipped
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


def board_punches(a, probe, dur, hook_end, skipped):
    """One punch per --punch-at beat (scene-local), centred on her steady face or on the product."""
    hist = None
    if a.product:
        import cv2
        hist = ref_colour_model(cv2.imread(a.product))
    out = []
    for spec in a.punch_at:
        t0, t1, on = parse_span(spec, "auto")
        t1 = min(t1, dur - 0.5)
        tag = f"punch {t0:.1f}-{t1:.1f}s"
        if t1 - t0 < 1.0:
            skipped.append(f"{tag}: under 1 s inside the scene (end capped at dur - 0.5) — left out")
            continue
        if t0 < hook_end:
            skipped.append(f"{tag}: overlaps the hook card (ends {hook_end - 0.3:.1f}s) — left out")
            continue
        if any(t0 < p["end"] and p["start"] < t1 for p in out):
            skipped.append(f"{tag}: overlaps another punch — left out")
            continue
        face = probe(a.video, t0, t1, 0.25)["face"] if on in ("face", "auto") else None
        steady = face and face[1] >= 80 and face[3] - face[1] <= 420
        if steady:
            out.append({**punch_for(face, t0, t1), "on": "face"})
            continue
        if on == "face":
            skipped.append(f"{tag}: no steady face (box {face}) — left out; `:product` centres on the product")
            continue
        if not a.product:
            skipped.append(f"{tag}: no steady face and no --product to find the product by — left out")
            continue
        got, why = product_centre(a.video, t0, t1, hist, face)
        if not got:
            skipped.append(f"{tag}: product not located ({why}) — left out")
            continue
        out.append({"start": round(t0, 2), "end": round(t1, 2), "zoom": PUNCH_ZOOM, "cx": got[0], "cy": got[1],
                    "ease": 0.12, "on": "product:" + got[2]})
    return sorted(out, key=lambda p: p["start"]), skipped


def cmd_gfx(a):
    probe, grab = lp().probe, lp().frame
    with open(a.report, encoding="utf-8") as f:
        report = json.load(f)
    md, notes = None, []
    ref = a.product or a.product_sticker
    if ref:
        import cv2
        md = hue_model(cv2.imread(ref))
        if md is None:
            notes.append(f"product not located: {os.path.basename(ref)} is black / white / grey (no hue) — check by "
                         "eye that the cut-out and headlines miss it")
    wins = []
    for scene, t0, t1 in scene_windows(report):
        p = probe(a.video, t0, t1, 0.4)
        busy, prod = p["busy"], []
        for k in range(5):
            img = grab(a.video, t0 + 0.1 + (t1 - t0 - 0.2) * k / 4)
            if k in (0, 2, 4):
                busy = busy | detail_mask(img)
            box = product_box(img, md) if md else None
            if box:
                prod.append(box)                # the cut-out and the headlines never cover the real product
        wins.append({"scene": scene, "t0": t0, "t1": t1, "face": p["face"], "busy": busy, "product": prod})
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
    plan, skipped = plan_gfx(wins, hook)
    skipped += notes
    placed = []
    held = [(w["t0"], w["t1"], b) for w in wins for b in w["product"]]
    if a.product_sticker:
        import cv2
        im = cv2.imread(a.product_sticker)
        scenes = report.get("scenes") or []
        last0 = float(scenes[-1].get("global_start") or 0) if scenes else 0.0
        t0, t1, _ = parse_span(a.sticker_at) if a.sticker_at else (last0, float(report.get("v_dur") or 0), None)
        entry, note = place_product_sticker(wins, a.product_sticker, im.shape[1] / im.shape[0], t0, t1, hook)
        skipped.append(note)
        if entry:
            plan["image_stickers"] = [entry]
            r = image_rect(entry["x"], entry["y"], entry["h"], im.shape[1] / im.shape[0])
            placed.append((entry["start"], entry["end"], r))
            # a vector sticker under the cut-out would be hidden by it
            plan["stickers"] = [st for st in plan["stickers"] if not (st["start"] < entry["end"] and entry["start"] < st["end"]
                                and overlap((st["x"] - 40, st["y"] - 40, st["x"] + 40, st["y"] + 40), r))]
    specs = list(a.headline or [])
    for h in report.get("headlines") or []:      # post_presenter could not draw the CTA pill beside her head
        if not any(s.rpartition("@")[0] == h["text"] for s in specs):
            specs.append(f"{h['text']}@{h['start']}-{h['end']}")
    if specs:
        gl = graphics_layer()
        faces = [(av["start"], av["end"], av["rect"]) for av in plan["avoid"]]
        rect_fn = lambda text, size, y: gl.text_rect(text, size, 360, y)
        for spec in specs:
            text, _, span = spec.rpartition("@")
            if not text:
                sys.exit(f"--headline needs TEXT@T0-T1, got {spec!r}")
            t0, t1, _ = parse_span(span)
            entry, note = place_headline(text, t0, t1, faces, report.get("pills") or [], report.get("subs") or [],
                                         rect_fn, placed, held, report.get("sub_rects"))
            skipped.append(note)
            if entry:
                plan.setdefault("headlines", []).append(entry)
                placed.append((t0, t1, rect_fn(text, entry["size"], entry["y"])))
    return plan, skipped


def graphics_layer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("graphics_layer",
                                                  os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphics_layer.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    s.add_argument("--punch-at", action="append", default=[], metavar="T0-T1[:face|product|auto]")
    s = sub.add_parser("gfx")
    s.add_argument("video")
    s.add_argument("--report", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--fx1")
    s.add_argument("--product-sticker", metavar="IMG")
    s.add_argument("--product", metavar="REF", help="ref the product is located by (default: --product-sticker)")
    s.add_argument("--sticker-at", metavar="T0-T1")
    s.add_argument("--headline", action="append", default=[], metavar="TEXT@T0-T1")
    s = sub.add_parser("boxes")
    s.add_argument("video")
    s.add_argument("--product", required=True)
    s.add_argument("--at", required=True, metavar="T,T,…")
    a = ap.parse_args(argv)
    if a.cmd == "boxes":
        print(json.dumps(cmd_boxes(a)))
        return 0
    for f in [a.video] + ([a.report] + [x for x in (a.product_sticker, a.product) if x] if a.cmd == "gfx"
                          else [a.product] if a.product else []):
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
