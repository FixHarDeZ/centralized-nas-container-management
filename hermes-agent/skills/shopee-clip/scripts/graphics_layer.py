#!/usr/bin/env python3
"""Graphics layer v2 for the presenter+graphics preset (Fix 2026-11-07).

Runs on a FINISHED clip (post_presenter out.mp4, already has Thai subs + EN pills) and adds:
  * headlines   - Thai pop headlines, 4 animation styles, pink keyword highlight
  * stickers    - vector ASS stickers (sparkle/heart/arrow/check/ring/burst/star), animated
  * callouts    - ring on a product part + line + EN label (<=2 words)
  * badges      - numbered feature badges (1/2/3)
  * endcard     - product card image dropping in during the last beat + bouncing arrow
  * cover       - sticker over Flow's sparkle watermark for the whole clip
  * sfx         - pop / twinkle / whoosh, auto-added at each element's start
Subtitles and pills are NOT touched; pass --report <post_presenter report.json> so the
layout check can keep graphics out of the pill band and the subtitle band while they show.

Usage:
  python3 graphics_layer.py in.mp4 plan.json out.mp4 [--report report.json] [--check] [--fonts DIR]

plan.json (all keys optional, times = FINAL clip seconds):
{
  "headlines": [{"text": "ก้านเล็ก\\Nเข้าซอกง่าย", "hl": "ก้านเล็ก", "start": 0.3, "end": 2.6,
                 "y": 300, "style": "pop|stamp|bounce|wipe", "size": 58}],
  "stickers":  [{"kind": "sparkle", "x": 560, "y": 330, "size": 70, "start": 0.5, "end": 2.5,
                 "color": "yellow", "anim": "pop|twinkle|bounce|none"}],
  "callouts":  [{"label": "Soft Tip", "tx": 420, "ty": 520, "lx": 200, "ly": 380,
                 "start": 3.0, "end": 5.2, "color": "pink"}],
  "badges":    [{"n": 1, "x": 120, "y": 300, "start": 3.0, "end": 5.2, "color": "mint"}],
  "endcard":   {"image": "product.jpg", "start": 17.0, "end": 19.4, "y": 330, "w": 380, "x": 360,
                "arrow": true, "arrow_y": 760},   # x = card centre; put it beside the face, not on it
  "cover":     {"x": 650, "y": 1190, "size": 64, "kind": "sparkle", "color": "yellow"},
  "sfx":       [{"t": 1.0, "kind": "pop"}],   "auto_sfx": true, "sfx_gain": 0.35,
  "avoid":     [{"name": "face", "rect": [250, 300, 470, 560], "start": 0, "end": 20}],
  "image_stickers": [{"image": "cover.jpg", "x": 520, "y": 960, "h": 220, "rot": -6, "start": 2.0, "end": 17.5, "w_est": 160}]
}
`image_stickers` = a cut-out product / GAME COVER (white sticker border + shadow, slides in, bobs).
  Gameplay v5 layout (Fix 2026-11-07: "crop หน้าปกเกมมาแปะ ไม่บังจอ"): the footage window is y 280-690
  and subs y ~707-830, so the cover goes BELOW the subs at x≈520, y≈960, h≈220, rot -6 (clear of the
  right-rail icons x>=640 and the bottom-left caption text). Pass avoid [0,280,720,690] "footage",
  and keep it OFF full-bleed hero/cold-open shots (start after the cold open, end before the hero).
`avoid` = presenter face box (read it off 2-3 real frames with vision first); text-bearing
elements may not cover it. Flow presenters sit centre-frame, so headlines usually go to
y≈200 above the head or beside it at size 46-50, and callouts point at the product in hand.
Rules enforced (exit 2 on violation):
  * text-bearing elements (headline, callout label, badge) inside the safe box x80-592 / y192-832
  * no two text-bearing elements overlap in BOTH time and rect
  * with --report: no text-bearing element in the pill band (y186-262) while a pill shows,
    nor in the subtitle band (y700-835) while a sub shows
  * callout labels: ASCII only, <=2 words, nothing money-shaped
Output: FB-safe High/yuv420p/L4.0 bt709 faststart; audio re-encoded aac 48k stereo with a -4 dB limiter (AAC overshoots ~0.1 dB).
"""
import argparse, json, math, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.normpath(os.path.join(HERE, "..", "..", "gameplay-clips", "fonts"))
W, H = 720, 1280
SAFE = (80, 192, 592, 832)
PILL_BAND = (0, 186, W, 262)
SUB_BAND = (0, 700, W, 835)

# ASS colours are &HBBGGRR&
COL = {"pink": "&HB18FFF&", "yellow": "&H66D1FF&", "mint": "&H26C98A&", "purple": "&HFF5C7A&",
       "white": "&HFFFFFF&", "peach": "&H8CB4FF&", "sky": "&HF2C88A&"}
BROWN = "&H4A2A5A&"
HL = "&HA6B0FF&"   # pastel pink keyword

SHAPES = {  # drawn in a 100x100 box
    "sparkle": "m 50 0 b 56 38 62 44 100 50 b 62 56 56 62 50 100 b 44 62 38 56 0 50 b 38 44 44 38 50 0",
    "heart": "m 50 28 b 50 8 20 -2 8 18 b -2 38 18 62 50 92 b 82 62 102 38 92 18 b 80 -2 50 8 50 28",
    "arrow": "m 34 0 l 66 0 l 66 52 l 92 52 l 50 100 l 8 52 l 34 52",
    "check": "m 0 56 l 16 40 l 38 62 l 84 10 l 100 26 l 38 92",
    "ring": "m 50 0 b 78 0 100 22 100 50 b 100 78 78 100 50 100 b 22 100 0 78 0 50 b 0 22 22 0 50 0",
}


def _star(n, r_out=50, r_in=22):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = math.pi * i / n - math.pi / 2
        pts.append((50 + r * math.cos(a), 50 + r * math.sin(a)))
    return "m " + " l ".join(f"{x:.1f} {y:.1f}" for x, y in pts)


SHAPES["star"] = _star(5)
SHAPES["burst"] = _star(10, 50, 34)


def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def text_rect(text, size, cx, top, font="Itim-Regular.ttf", fonts=FONTS):
    """Approximate pixel rect of a centred (an8) multi-line ASS text."""
    from PIL import ImageFont
    f = ImageFont.truetype(os.path.join(fonts, font), size)
    lines = text.replace("\\N", "\n").split("\n")
    w = max(f.getlength(l) for l in lines) + 2 * 6
    h = len(lines) * size * 1.3 + 2 * 6
    return (cx - w / 2, top, cx + w / 2, top + h)


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def head_tag(style, y, dur_ms):
    base = f"\\an8\\fad(0,150)"
    if style == "stamp":
        return base + f"\\pos(360,{y})\\frz-3\\fscx175\\fscy175\\alpha&HFF&\\t(0,150,\\fscx100\\fscy100\\alpha&H00&)"
    if style == "bounce":
        return base + (f"\\move(360,{y-90},360,{y},0,230)\\t(230,320,\\fscy88\\fscx108)"
                       f"\\t(320,420,\\fscy100\\fscx100)")
    if style == "wipe":
        return base + f"\\pos(360,{y})\\clip(0,0,0,{H})\\t(0,420,\\clip(0,0,{W},{H}))"
    return base + f"\\pos(360,{y})\\fscx60\\fscy60\\frz-6\\t(0,180,\\fscx100\\fscy100\\frz0)"  # pop


def sticker_ev(st, layer=3):
    kind = st.get("kind", "sparkle")
    if kind not in SHAPES:
        sys.exit(f"PLAN ERROR: unknown sticker kind '{kind}' (have {sorted(SHAPES)})")
    x, y, size = int(st["x"]), int(st["y"]), int(st.get("size", 70))
    c = COL.get(st.get("color", "yellow"), st.get("color"))
    s, e = float(st["start"]), float(st["end"])
    dur = int((e - s) * 1000)
    sc = size  # shape is 100 units -> scale% == px
    anim = st.get("anim", "pop")
    rot = st.get("rot", 0)
    fill = f"\\1c{c}\\3c{BROWN}\\bord3\\shad0"
    if kind == "ring":
        fill = f"\\1a&HFF&\\3c{c}\\bord{max(4, size // 14)}\\shad0"
    t = f"\\an5\\pos({x},{y})\\frz{rot}{fill}\\fad(0,120)"
    if anim == "pop":
        t += f"\\fscx0\\fscy0\\t(0,140,\\fscx{int(sc*1.2)}\\fscy{int(sc*1.2)})\\t(140,240,\\fscx{sc}\\fscy{sc})"
    elif anim == "twinkle":
        t += f"\\fscx{sc}\\fscy{sc}"
        step = 300
        for k in range(0, max(dur - step, 1), step):
            big = (k // step) % 2 == 0
            v = int(sc * (1.18 if big else 0.86))
            t += f"\\t({k},{k+step},\\fscx{v}\\fscy{v}\\frz{rot + (12 if big else -12)})"
    elif anim == "bounce":
        t = f"\\an5\\move({x},{y-14},{x},{y+14})\\frz{rot}{fill}\\fad(0,120)\\fscx{sc}\\fscy{sc}"
        # \move is linear; add a squash pulse every 400 ms for the "boing" feel
        for k in range(0, max(dur - 400, 1), 400):
            t += f"\\t({k},{k+200},\\fscy{int(sc*0.88)})\\t({k+200},{k+400},\\fscy{sc})"
    else:
        t += f"\\fscx{sc}\\fscy{sc}"
    return f"Dialogue: {layer},{ass_time(s)},{ass_time(e)},Shape,,0,0,0,,{{{t}\\p1}}{SHAPES[kind]}{{\\p0}}"


def callout_evs(c):
    s, e = float(c["start"]), float(c["end"])
    tx, ty, lx, ly = (int(c[k]) for k in ("tx", "ty", "lx", "ly"))
    col = COL.get(c.get("color", "pink"), c.get("color"))
    evs = [sticker_ev({"kind": "ring", "x": tx, "y": ty, "size": int(c.get("ring", 76)),
                       "start": s, "end": e, "color": c.get("color", "pink"), "anim": "pop"}, layer=4)]
    # line from label edge to ring edge (thick quad, absolute coords)
    dx, dy = tx - lx, ty - ly
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    r = int(c.get("ring", 76)) / 2 + 4
    x0, y0 = lx + ux * 34, ly + uy * 34
    x1, y1 = tx - ux * r, ty - uy * r
    nx, ny = -uy * 3, ux * 3
    quad = (f"m {x0+nx:.0f} {y0+ny:.0f} l {x1+nx:.0f} {y1+ny:.0f} l {x1-nx:.0f} {y1-ny:.0f} "
            f"l {x0-nx:.0f} {y0-ny:.0f}")
    evs.append(f"Dialogue: 4,{ass_time(s+0.08)},{ass_time(e)},Shape,,0,0,0,,"
               f"{{\\an7\\pos(0,0)\\1c&HFFFFFF&\\3c{BROWN}\\bord2\\shad0\\fad(120,120)\\p1}}{quad}{{\\p0}}")
    evs.append(f"Dialogue: 5,{ass_time(s+0.12)},{ass_time(e)},Label,,0,0,0,,"
               f"{{\\an5\\pos({lx},{ly})\\3c{col}\\fscx0\\fscy0\\t(0,160,\\fscx108\\fscy108)"
               f"\\t(160,240,\\fscx100\\fscy100)\\fad(0,120)}}{c['label']}")
    return evs


def badge_evs(b):
    s, e = float(b["start"]), float(b["end"])
    x, y = int(b["x"]), int(b["y"])
    col = COL.get(b.get("color", "mint"), b.get("color"))
    circ = SHAPES["ring"]
    return [f"Dialogue: 5,{ass_time(s)},{ass_time(e)},Shape,,0,0,0,,{{\\an5\\pos({x},{y})\\1c{col}\\3c{BROWN}"
            f"\\bord4\\shad0\\fad(0,120)\\fscx0\\fscy0\\t(0,150,\\fscx70\\fscy70)\\t(150,240,\\fscx62\\fscy62)\\p1}}"
            f"{circ}{{\\p0}}",
            f"Dialogue: 6,{ass_time(s+0.05)},{ass_time(e)},Badge,,0,0,0,,{{\\an5\\pos({x},{y+1})\\fad(80,120)}}{int(b['n'])}"]


def build_ass(plan, path):
    hdr = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
           "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
           "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
           "Alignment, MarginL, MarginR, MarginV, Encoding",
           "Style: Head,Itim,58,&H00FFFFFF,&H00FFFFFF,&H00203050,&H60203050,1,0,0,0,100,100,0,0,1,5,2.5,8,40,40,0,1",
           "Style: Shape,Arial,20,&H00FFFFFF,&H00FFFFFF,&H004A2A5A,&H00000000,0,0,0,0,100,100,0,0,1,3,0,5,0,0,0,1",
           "Style: Label,FredokaSB,36,&H00FFFFFF,&H00FFFFFF,&H00B18FFF,&H00000000,0,0,0,0,100,100,0,0,3,10,0,5,0,0,0,1",
           "Style: Badge,FredokaSB,40,&H00FFFFFF,&H00FFFFFF,&H004A2A5A,&H00000000,0,0,0,0,100,100,0,0,1,3,0,5,0,0,0,1",
           "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    ev = []
    for h in plan.get("headlines", []):
        s, e = float(h["start"]), float(h["end"])
        y = int(h.get("y", 300)); size = int(h.get("size", 58))
        txt = h["text"].replace("\n", "\\N")
        hl = h.get("hl")
        if hl and hl in txt:
            txt = txt.replace(hl, "{\\c" + HL + "\\fscx108\\fscy108}" + hl + "{\\c&HFFFFFF&\\fscx100\\fscy100}", 1)
        tag = head_tag(h.get("style", "pop"), y, int((e - s) * 1000))
        if size != 58:
            tag += f"\\fs{size}"
        ev.append(f"Dialogue: 2,{ass_time(s)},{ass_time(e)},Head,,0,0,0,,{{{tag}}}{txt}")
    for st in plan.get("stickers", []):
        ev.append(sticker_ev(st))
    for c in plan.get("callouts", []):
        ev += callout_evs(c)
    for b in plan.get("badges", []):
        ev += badge_evs(b)
    cv = plan.get("cover")
    if cv:
        ev.append(sticker_ev({"kind": cv.get("kind", "sparkle"), "x": cv["x"], "y": cv["y"],
                              "size": cv.get("size", 64), "color": cv.get("color", "yellow"),
                              "start": 0, "end": cv.get("end", 3600), "anim": "twinkle"}, layer=7))
    ec = plan.get("endcard")
    if ec and ec.get("arrow", True):
        ay = int(ec.get("arrow_y", int(ec.get("y", 330)) + int(ec.get("w", 380)) + 40))
        ev.append(sticker_ev({"kind": "arrow", "x": int(ec.get("x", 360)), "y": min(ay, 800), "size": 64, "color": "pink",
                              "start": float(ec["start"]) + 0.3, "end": ec["end"], "anim": "bounce"}, layer=6))
    open(path, "w", encoding="utf-8").write("\n".join(hdr + ev) + "\n")
    return len(ev)


def layout_check(plan, report, fonts):
    items = []  # (name, t0, t1, rect)
    for h in plan.get("headlines", []):
        r = text_rect(h["text"], int(h.get("size", 58)), 360, int(h.get("y", 300)), fonts=fonts)
        items.append((f"headline '{h['text'][:14]}'", float(h["start"]), float(h["end"]), r))
    for c in plan.get("callouts", []):
        lab = c["label"]
        if not lab.isascii() or len(lab.split()) > 2:
            yield f"callout label '{lab}' must be ASCII and <=2 words"
        if re.search(r"[$฿€£¥%]|\b\d+\s*(baht|thb|off)\b|\bsale\b|\bfree\b", lab, re.I):
            yield f"callout label '{lab}' looks like price/promo text"
        x0, y0, x1, y1 = text_rect(lab, 36, int(c["lx"]), int(c["ly"]) - 26, font="FredokaSB-Static.ttf", fonts=fonts)
        items.append((f"callout '{lab}'", float(c["start"]), float(c["end"]), (x0 - 10, y0 - 10, x1 + 10, y1 + 10)))
    for b in plan.get("badges", []):
        x, y = int(b["x"]), int(b["y"])
        items.append((f"badge {b['n']}", float(b["start"]), float(b["end"]), (x - 32, y - 32, x + 32, y + 32)))
    for n, t0, t1, r in items:
        if r[0] < SAFE[0] or r[1] < SAFE[1] or r[2] > SAFE[2] or r[3] > SAFE[3]:
            yield f"{n} rect {tuple(int(v) for v in r)} leaves the safe box {SAFE}"
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a[1] < b[2] and b[1] < a[2] and overlap(a[3], b[3]):
                yield f"{a[0]} collides with {b[0]} ({max(a[1], b[1]):.2f}-{min(a[2], b[2]):.2f}s)"
    for im in plan.get("image_stickers", []):
        h_ = int(im.get("h", 200)); w_ = int(im.get("w_est", h_ * 0.8)) + 42
        r = (int(im["x"]) - w_ / 2, int(im["y"]) - (h_ + 42) / 2, int(im["x"]) + w_ / 2, int(im["y"]) + (h_ + 42) / 2)
        for av in plan.get("avoid", []):
            if float(im.get("start", 0)) < float(av.get("end", 3600)) and float(av.get("start", 0)) < float(im.get("end", 3600)) \
                    and overlap(r, tuple(av["rect"])):
                yield f"image sticker '{os.path.basename(im['image'])}' covers avoid-zone '{av.get('name', 'zone')}'"
        if report:
            for s0, s1, txt in report.get("subs", []):
                if float(im.get("start", 0)) < s1 and s0 < float(im.get("end", 3600)) and overlap(r, SUB_BAND):
                    yield f"image sticker '{os.path.basename(im['image'])}' sits in the subtitle band"
                    break
    for av in plan.get("avoid", []):   # e.g. presenter face box read off a frame by vision
        ar = tuple(av["rect"]); a0, a1 = float(av.get("start", 0)), float(av.get("end", 3600))
        for n, t0, t1, r in items:
            if t0 < a1 and a0 < t1 and overlap(r, ar):
                yield f"{n} covers avoid-zone '{av.get('name', 'face')}' {ar}"
    if report:
        for c in plan.get("callouts", []):   # the leader LINE must not cut through a showing subtitle
            seg = (min(c["lx"], c["tx"]), min(c["ly"], c["ty"]), max(c["lx"], c["tx"]), max(c["ly"], c["ty"]))
            for s0, s1, txt in report.get("subs", []):
                if float(c["start"]) < s1 and s0 < float(c["end"]) and overlap(seg, SUB_BAND):
                    yield f"callout '{c['label']}' line crosses the subtitle band while sub '{txt[:12]}' shows"
                    break
        for n, t0, t1, r in items:
            for p0, p1, txt in report.get("pills", []):
                if t0 < p1 and p0 < t1 and overlap(r, PILL_BAND):
                    yield f"{n} sits in the pill band while pill '{txt}' shows ({p0}-{p1})"
            for s0, s1, txt in report.get("subs", []):
                if t0 < s1 and s0 < t1 and overlap(r, SUB_BAND):
                    yield f"{n} sits in the subtitle band while sub '{txt[:12]}' shows ({s0}-{s1})"
                    break


def make_card(src, out, w=380):
    """Product photo -> rounded white-border card with soft shadow (RGBA PNG)."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(src).convert("RGB")
    s = (w - 24) / im.width
    im = im.resize((w - 24, int(im.height * s)), Image.LANCZOS)
    cw, ch = w, im.height + 24
    pad = 24
    card = Image.new("RGBA", (cw + 2 * pad, ch + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", card.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 8, pad + cw, pad + ch + 8), 34, fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    card.paste((90, 42, 74, 255), (0, 0), sh)
    body = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    m = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, cw, ch), 34, fill=255)
    pm = Image.new("L", im.size, 0)
    ImageDraw.Draw(pm).rounded_rectangle((0, 0, im.width, im.height), 24, fill=255)
    body.paste(im, (12, 12), pm)
    card.paste(body, (pad, pad), m)
    card.save(out)
    return card.size


def make_sfx(wd):
    out = {}
    specs = {
        # falling chirp 900 -> 300 Hz over 0.12 s: phase = 900t - 2500t^2
        "pop": "aevalsrc='0.7*sin(2*PI*(900*t-2500*t*t))*exp(-30*t)':s=48000:d=0.12",
        "twinkle": "aevalsrc='0.35*(sin(2*PI*2093*t)*exp(-14*t)+sin(2*PI*2637*max(t-0.07,0))*exp(-14*max(t-0.07,0))*gte(t,0.07)"
                   "+sin(2*PI*3136*max(t-0.14,0))*exp(-12*max(t-0.14,0))*gte(t,0.14))':s=48000:d=0.5",
    }
    for k, src in specs.items():
        p = os.path.join(wd, f"{k}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, "-af",
                        "aformat=channel_layouts=stereo,alimiter=limit=0.5:level=0", "-ar", "48000", p], check=True)
        out[k] = p
    wh = os.path.normpath(os.path.join(HERE, "..", "..", "gameplay-clips", "assets", "sfx", "whoosh.wav"))
    if os.path.exists(wh):
        out["whoosh"] = wh
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--fonts", default=FONTS)
    ap.add_argument("--report", help="post_presenter report.json (pills/subs timing for the layout check)")
    ap.add_argument("--check", action="store_true", help="layout check only, no render")
    a = ap.parse_args()
    pdir = os.path.dirname(os.path.abspath(a.plan))
    plan = json.load(open(a.plan, encoding="utf-8"))
    report = json.load(open(a.report, encoding="utf-8")) if a.report else None
    hs = sorted(plan.get("headlines", []), key=lambda h: float(h["start"]))
    for x, y in zip(hs, hs[1:]):
        if float(y["start"]) < float(x["end"]) - 1e-6:
            sys.exit(f"PLAN ERROR: headline '{y['text']}' overlaps '{x['text']}'")
    probs = list(layout_check(plan, report, a.fonts))
    for p in probs:
        print("LAYOUT:", p)
    if probs:
        sys.exit(2)
    print("layout OK" + ("" if report else " (no --report: pill/sub bands not checked)"))
    if a.check:
        return
    wd = tempfile.mkdtemp(prefix="gfx_", dir=os.environ.get("TMPDIR", "/opt/data/cache/scratch"))
    ass = os.path.join(wd, "gfx.ass")
    n_ev = build_ass(plan, ass)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                a.src], capture_output=True, text=True, check=True).stdout.strip())
    ins = ["-i", a.src]
    fv, fa = [], []
    vl = "0:v"
    for k, im in enumerate(plan.get("image_stickers", [])):
        sys.path.insert(0, HERE)
        from presenter_fx import cutout_png
        src = im["image"] if os.path.isabs(im["image"]) else os.path.join(pdir, im["image"])
        png = os.path.join(wd, f"imst{k}.png")
        cw, chh = cutout_png(src, png, int(im.get("h", 200)))
        if im.get("rot"):   # slight tilt reads as a deliberate sticker, not a misplaced box
            from PIL import Image
            rp = Image.open(png).rotate(float(im["rot"]), resample=Image.BICUBIC, expand=True)
            rp.save(png); cw, chh = rp.size
        s0, e0 = float(im.get("start", 0)), float(im.get("end", dur))
        n_in = len(ins) // 2 if False else None
        ins += ["-loop", "1", "-t", f"{dur:.3f}", "-i", png]
        idx_in = sum(1 for x in ins if x == "-i") - 1
        x0, y0 = int(im["x"]) - cw // 2, int(im["y"]) - chh // 2
        fv.append(f"[{idx_in}:v]format=rgba,fade=t=in:st={s0}:d=0.2:alpha=1,"
                  f"fade=t=out:st={max(s0, e0 - 0.2):.3f}:d=0.2:alpha=1[ims{k}]")
        fv.append(f"[{vl}][ims{k}]overlay=x={x0}:y='{y0}+40*max(0\\,1-(t-{s0})/0.25)+5*sin(2*PI*(t-{s0})/1.4)'"
                  f":enable='between(t,{s0},{e0})'[vi{k}]")
        vl = f"vi{k}"
    ec = plan.get("endcard")
    if ec:
        img = ec["image"] if os.path.isabs(ec["image"]) else os.path.join(pdir, ec["image"])
        cw, chh = make_card(img, os.path.join(wd, "card.png"), int(ec.get("w", 380)))
        s, e = float(ec["start"]), float(ec["end"])
        ins += ["-loop", "1", "-t", f"{dur:.3f}", "-i", os.path.join(wd, "card.png")]
        ec_idx = sum(1 for x in ins if x == "-i") - 1
        y0 = int(ec.get("y", 330)) - 24
        fv.append(f"[{ec_idx}:v]format=rgba,fade=t=in:st={s}:d=0.18:alpha=1,fade=t=out:st={e-0.15}:d=0.15:alpha=1[card]")
        cx_ = int(ec.get("x", W // 2))
        fv.append(f"[{vl}][card]overlay=x={cx_ - cw//2}:y='{y0}-60*max(0\\,1-(t-{s})/0.22)'"
                  f":enable='between(t,{s},{e})'[vc]")
        vl = "vc"
    fv.append(f"[{vl}]ass={ass}:fontsdir={os.path.abspath(a.fonts)}:shaping=complex,format=yuv420p,"
              f"setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[vout]")
    # sfx
    hits = list(plan.get("sfx", []))
    if plan.get("auto_sfx", True):
        for h in plan.get("headlines", []):
            hits.append({"t": float(h["start"]), "kind": "pop"})
        for c in plan.get("callouts", []) + plan.get("badges", []):
            hits.append({"t": float(c["start"]), "kind": "pop"})
        for st in plan.get("stickers", []):
            hits.append({"t": float(st["start"]), "kind": "twinkle" if st.get("kind") in ("sparkle", "star", "burst") else "pop"})
        if ec:
            hits.append({"t": float(ec["start"]), "kind": "whoosh"})
        for im in plan.get("image_stickers", []):
            hits.append({"t": float(im.get("start", 0)), "kind": "pop"})
    # dedupe hits closer than 0.15 s
    hits.sort(key=lambda h: h["t"])
    ded = []
    for h in hits:
        if not ded or h["t"] - ded[-1]["t"] > 0.15:
            ded.append(h)
    sfx = make_sfx(wd) if ded else {}
    ded = [h for h in ded if h["kind"] in sfx]
    idx = {}
    for k in sorted({h["kind"] for h in ded}):
        ins += ["-i", sfx[k]]
        idx[k] = sum(1 for x in ins if x == "-i") - 1
    g = float(plan.get("sfx_gain", 0.35))
    labels = []
    for i, h in enumerate(ded):
        fa.append(f"[{idx[h['kind']]}:a]volume={g},adelay={int(h['t']*1000)}:all=1[s{i}]")
        labels.append(f"[s{i}]")
    if labels:
        fa.append(f"[0:a]{''.join(labels)}amix=inputs={len(labels)+1}:duration=first:normalize=0,"
                  f"alimiter=limit=0.63:level=0,aresample=48000[aout]")
        amap = ["-map", "[aout]"]
    else:
        amap = ["-map", "0:a?"]
    cmd = ["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(fv + fa),
           "-map", "[vout]", *amap, "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print(f"OK {a.out} events={n_ev} sfx={len(ded)} endcard={'yes' if ec else 'no'} workdir={wd}")


if __name__ == "__main__":
    main()
