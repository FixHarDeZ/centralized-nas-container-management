#!/usr/bin/env python3
"""Presenter pre-pass (Fix 2026-11-07): punch-in zooms + product insert cutaways on ONE raw
Flow scene, BEFORE post_presenter.py. Video only - the scene's audio is copied untouched, so
post_presenter's ASR/sub timing and the duration stay exactly the same (0 credits).

Usage:
  python3 presenter_fx.py scene_raw.mp4 fx.json scene_fx.mp4

fx.json (scene-LOCAL seconds of the RAW file):
{
  "punch":   [{"start": 2.4, "end": 5.0, "zoom": 1.12, "cx": 360, "cy": 520, "ease": 0.12}],
  "inserts": [{"image": "product_clean.jpg", "start": 5.2, "dur": 0.7, "bg": "pink"}],
  "hook_card": {"image": "product_clean.jpg", "dur": 0.9, "bg": "yellow"}   # covers 0..dur
}
DEFAULT since Fix's pick (2026-11-07): add "mode": "overlay", "x", "y" (centre), "h" (px) to any
insert / hook_card -> the product is CUT OUT (background removed) and placed beside the presenter
instead of a full-screen card, so she is never hidden. Read the empty backdrop rect off real frames
with vision first (typically right side x 520-720, y 260-555).
* punch: zoom snaps in over `ease` s (default 0.12 = reads as a jump-cut on the beat) and snaps
  back at `end`; (cx,cy) is the point to keep centred (presenter face / product in hand).
  Keep zoom <= 1.15 - Flow's 720p gets soft above that.
* inserts / hook_card: full-screen product card (pastel bg + white rounded card + sparkles) with
  a slow 1.00->1.05 push-in. The VO keeps running underneath; use them on a word that names the
  product, or to hide a seam / a looped phrase. hook_card = the cold open (the product in the
  first second, before the presenter's face).
Then feed scene_fx.mp4 to post_presenter.py as that scene's `video`.
"""
import json, math, os, subprocess, sys, tempfile

W, H, FPS = 720, 1280, 24
BG = {"pink": (255, 214, 226), "yellow": (255, 240, 196), "mint": (210, 244, 226),
      "lavender": (232, 222, 255), "peach": (255, 224, 206), "sky": (210, 232, 255)}


def card_full(src, out, bg="pink"):
    from PIL import Image, ImageDraw, ImageFilter
    c0 = BG.get(bg, BG["pink"])
    c1 = tuple(min(255, v + 22) for v in c0)
    canvas = Image.new("RGB", (W, H), c0)
    d = ImageDraw.Draw(canvas)
    for y in range(H):  # vertical gradient
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] * (1 - k) + c0[i] * k) for i in range(3)))
    # soft dots pattern
    for i in range(0, W, 90):
        for j in range(0, H, 90):
            d.ellipse((i + (j // 90 % 2) * 45, j, i + (j // 90 % 2) * 45 + 10, j + 10),
                      fill=tuple(min(255, v + 30) for v in c0))
    im = Image.open(src).convert("RGB")
    maxw, maxh = 500, 400
    s = min(maxw / im.width, maxh / im.height)
    im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    cw, ch = im.width + 36, im.height + 36
    x0, y0 = (W - cw) // 2, 262 + (436 - ch) // 2      # y 262-698: below the pill band, ABOVE the subtitle band (subs must not cover the product)
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 12, x0 + cw, y0 + ch + 12), 40, fill=120)
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    canvas.paste((120, 60, 90), (0, 0), sh)
    m = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, cw, ch), 40, fill=255)
    canvas.paste((255, 255, 255), (x0, y0), m)
    pm = Image.new("L", im.size, 0)
    ImageDraw.Draw(pm).rounded_rectangle((0, 0, im.width, im.height), 28, fill=255)
    canvas.paste(im, (x0 + 18, y0 + 18), pm)

    def sparkle(cx, cy, r, col=(255, 209, 102)):
        pts = []
        for k in range(8):
            rr = r if k % 2 == 0 else r * 0.28
            a = math.pi * k / 4 - math.pi / 2
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=col, outline=(90, 42, 74))
    d = ImageDraw.Draw(canvas)
    sparkle(x0 + cw - 10, y0 + 6, 34)
    sparkle(x0 + 8, y0 + ch - 20, 24, (255, 143, 177))
    sparkle(x0 + cw + 10, y0 + ch // 2, 16, (255, 255, 255))
    canvas.save(out, quality=95)


def cutout_png(src, out, h=260, outline=7):
    """Product photo on a plain light background -> RGBA sticker: background removed by an
    edge flood-fill (so cream/white parts INSIDE the product survive), white sticker outline,
    soft drop shadow. Returns (w, h) of the PNG."""
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
    im = Image.open(src).convert("RGB")
    s = h / im.height
    im = im.resize((max(1, int(im.width * s)), h), Image.LANCZOS)
    # flood-fill near-white from the border on a padded copy
    pad = 4
    big = Image.new("RGB", (im.width + 2 * pad, im.height + 2 * pad), (255, 255, 255))
    big.paste(im, (pad, pad))
    ImageDraw.floodfill(big, (0, 0), (255, 0, 255), thresh=38)
    mag = Image.new("RGB", big.size, (255, 0, 255))
    diff = ImageChops.difference(big, mag).convert("L")
    alpha = diff.point(lambda v: 255 if v > 8 else 0).crop((pad, pad, pad + im.width, pad + im.height))
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    M = outline + 14
    W2, H2 = im.width + 2 * M, im.height + 2 * M
    a_big = Image.new("L", (W2, H2), 0); a_big.paste(alpha, (M, M))
    ring = a_big.filter(ImageFilter.MaxFilter(2 * outline + 1)).filter(ImageFilter.GaussianBlur(1))
    shadow = ring.filter(ImageFilter.GaussianBlur(7)).point(lambda v: int(v * 0.45))
    canvas = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    canvas.paste((90, 42, 74, 255), (0, 6), shadow)          # brown soft shadow, offset down
    canvas.paste((255, 255, 255, 255), (0, 0), ring)          # white sticker border
    prod = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); prod.paste(im, (M, M))
    canvas.paste(prod, (0, 0), a_big)
    canvas.save(out)
    return canvas.size


def zoom_expr(punch):
    if not punch:
        return "1"
    terms = []
    for p in punch:
        s, e, z, ea = float(p["start"]), float(p["end"]), float(p.get("zoom", 1.12)), float(p.get("ease", 0.12))
        if z > 1.2:
            sys.exit(f"FX ERROR: zoom {z} > 1.2 (720p source goes soft)")
        terms.append(f"{z-1:.4f}*clip((t-{s})/{ea},0,1)*lt(t,{e})")
    return "1+" + "+".join(terms)


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, fxp, out = sys.argv[1:]
    fx = json.load(open(fxp, encoding="utf-8"))
    pdir = os.path.dirname(os.path.abspath(fxp))
    P = lambda p: p if os.path.isabs(p) else os.path.join(pdir, p)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                               capture_output=True, text=True, check=True).stdout.strip())
    wd = tempfile.mkdtemp(prefix="pfx_", dir=os.environ.get("TMPDIR", "/opt/data/cache/scratch"))
    punch = fx.get("punch", [])
    # per-window centre: piecewise cx/cy (default 360/640)
    cx = "+".join(f"({int(p.get('cx', 360))}-360)*between(t,{p['start']},{p['end']})" for p in punch) or "0"
    cy = "+".join(f"({int(p.get('cy', 640))}-640)*between(t,{p['start']},{p['end']})" for p in punch) or "0"
    Z = zoom_expr(punch)
    # scale up by Z then crop back to 720x1280 around (360+cx', 640+cy') scaled
    fv = [f"[0:v]fps={FPS},scale=w='trunc({W}*({Z})/2)*2':h='trunc({H}*({Z})/2)*2':eval=frame,"
          f"crop={W}:{H}:x='clip((360+({cx}))*iw/{W}-360,0,iw-{W})':y='clip((640+({cy}))*ih/{H}-640,0,ih-{H})',"
          f"setsar=1,format=yuv420p[b0]"]
    ins = ["-i", src]
    cards = list(fx.get("inserts", []))
    if fx.get("hook_card"):
        hc = dict(fx["hook_card"]); hc["start"] = 0.0
        cards.insert(0, hc)
    vl = "b0"
    for i, c in enumerate(cards):
        if c.get("mode") == "overlay":   # product cutout sticker beside the presenter (Fix's pick 2026-11-07)
            png = os.path.join(wd, f"cut{i}.png")
            cw, chh = cutout_png(P(c["image"]), png, int(c.get("h", 260)))
            s, d_ = float(c["start"]), float(c["dur"])
            x0, y0 = int(c["x"]) - cw // 2, int(c["y"]) - chh // 2
            ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", png]
            fv.append(f"[{i+1}:v]format=rgba,fade=t=in:st={s}:d=0.15:alpha=1,"
                      f"fade=t=out:st={s+d_-0.15:.3f}:d=0.15:alpha=1[c{i}]")
            # slide up 40 px while fading in, then a gentle 6 px bob
            fv.append(f"[{vl}][c{i}]overlay=x={x0}:y='{y0}+40*max(0\\,1-(t-{s})/0.2)+6*sin(2*PI*(t-{s})/1.2)'"
                      f":enable='between(t,{s},{s+d_})'[o{i}]")
            vl = f"o{i}"
            continue
        img = os.path.join(wd, f"card{i}.jpg")
        card_full(P(c["image"]), img, c.get("bg", "pink"))
        s, d_ = float(c["start"]), float(c["dur"])
        n = max(1, int(round(d_ * FPS)))
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d_:.3f}", "-i", img]
        k = len(ins) // 2 - 1 if False else i + 1
        fv.append(f"[{k}:v]scale={W*2}:{H*2},zoompan=z='1+0.05*on/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
                  f":d=1:s={W}x{H}:fps={FPS},format=yuv420p,setpts=PTS-STARTPTS+{s}/TB[c{i}]")
        fv.append(f"[{vl}][c{i}]overlay=eof_action=pass:enable='between(t,{s},{s+d_})'[o{i}]")
        vl = f"o{i}"
    fv.append(f"[{vl}]setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[vout]")
    cmd = ["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(fv), "-map", "[vout]", "-map", "0:a?",
           "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-level", "4.0", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-color_range", "tv", "-c:a", "copy", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    print(f"OK {out} punch={len(punch)} cards={len(cards)} dur={dur:.3f}")


if __name__ == "__main__":
    main()
