#!/usr/bin/env python3
"""Keep a burned Thai subtitle off the product the presenter holds.

The subtitle sits in a fixed band (bottom y 815, 2 lines ~ y 690-815, x 60-580): chest height, which is exactly
where Flow puts a held product however the prompt asks for "beside her cheek". 2026-11-27 all three 🧑 clips
(keem, airnub, decker) ran a sub across the product: the case and driver at 5.4-7.5 s, the drill at 5.4-9.6 s.

post_presenter measures the product box at 3 moments of each subtitle event (`autogfx.py boxes`, the ref's hue)
and the head box (pillclear), and `choose()` picks where that event goes. The overlap of a rect with the product
is the worst moment's max(share of the product it covers, share of the sub drawn on the product): a union of the
boxes over a cut reads small against its own size while the one-line "แบตสองก้อน" sat right on the battery.
  * a moment whose product box fills > CLOSE_UP of the frame (an insert close-up: nothing can miss it) is left
    out; no moment left -> kept;
  * overlap <= COVER_MAX -> kept where it is;
  * else the nearest rect (bottom y, centre x) inside the safe box (x 60-580, y 270-832: under the pill band,
    above the bottom-UI band) that misses the head and overlaps the least — moved when that brings it under
    COVER_MAX, halves it, or cuts it by GAIN (decker 5.8-8.1: 0.75 -> 0.40, the drill's tip instead of its body);
  * nothing better -> left in the band ("stuck": a close-up insert the product fills), a report note, never on
    the face.
With no head measured the sub never climbs above its band (it could land on a face it cannot see).
Pure geometry, no I/O: unit-tested in test_subclear.py.
"""
W, H = 720, 1280
X_LO, X_HI = 60, 580          # sub text area (safe-zones.md; the style's MarginL 60 / MarginR 140)
Y_TOP, Y_BOT = 270, 832       # under the pill band (196-262) / the bottom-UI band starts at 832
LINE_H = 58                   # Itim at 48 px: ascent 46 + descent 12
OUTLINE = 6                   # Outline 5 + shadow
COVER_MAX = 0.2               # overlap (see covered) a sub may have with the product and stay put
GAIN = 0.25                   # an overlap cut by this much is worth the move
CLOSE_UP = 0.3                # a product box over this share of the frame = an insert close-up, not avoidable
FACE_PAD = 12
STEP = 10


def area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def size(line_widths):
    """Text widths of the lines (px at the render size) -> (w, h) of the drawn subtitle."""
    return max(line_widths) + 2 * OUTLINE, len(line_widths) * LINE_H + 2 * OUTLINE


def rect(cx, yb, w, h):
    return (cx - w / 2, yb - h, cx + w / 2, yb)


def covered(r, prods):
    """Worst moment: max over the product boxes of max(share of the box under r, share of r over the box)."""
    out = 0.0
    for b in prods:
        if b and area(b):
            i = inter(r, b)
            out = max(out, i / area(b), i / area(r))
    return out


def choose(w, h, prods, face, mv=465, ml=60, mr=140):
    """prods = the product box at each sampled moment (None = not found) -> {"how": kept|moved|stuck, "cx",
    "yb", "cover", "cover0", "rect"}."""
    prods = [b for b in ([prods] if prods and not isinstance(prods[0], (list, tuple)) else prods or [])
             if b and area(b) <= CLOSE_UP * W * H]
    cx0, yb0 = (ml + W - mr) / 2, H - mv
    r0 = rect(cx0, yb0, w, h)
    c0 = covered(r0, prods)
    res = {"how": "kept", "cx": cx0, "yb": yb0, "cover": round(c0, 2), "cover0": round(c0, 2), "rect": r0}
    if c0 <= COVER_MAX:
        return res
    fr = (face[0] - FACE_PAD, face[1] - FACE_PAD, face[2] + FACE_PAD, face[3] + FACE_PAD) if face else None
    xs = list(range(int(X_LO + w / 2), int(X_HI - w / 2) + 1, STEP)) or [int(cx0)]
    best = None
    for yb in range(Y_BOT, int(Y_TOP + h) - 1, -STEP):
        if fr is None and yb < yb0:
            continue
        for cx in xs:
            r = rect(cx, yb, w, h)
            if fr and inter(r, fr) > 0:
                continue
            c = covered(r, prods)
            cost = c + abs(yb - yb0) / 2000 + abs(cx - cx0) / 4000
            if best is None or cost < best[0]:
                best = (cost, cx, yb, c, r)
    if best and (best[3] <= COVER_MAX or best[3] <= c0 / 2 or best[3] <= c0 - GAIN):
        return {"how": "moved", "cx": best[1], "yb": best[2], "cover": round(best[3], 2), "cover0": round(c0, 2),
                "rect": best[4]}
    return {**res, "how": "stuck"}


def margins(choice, w):
    """ASS Dialogue MarginL / MarginR / MarginV that draw the sub at the chosen place (alignment 2, no wrap)."""
    ml = round(choice["cx"] - w / 2 - 4)
    mr = round(W - (choice["cx"] + w / 2 + 4))
    return max(1, ml), max(1, mr), max(1, round(H - choice["yb"]))
