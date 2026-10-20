"""Pitch → Product Clip (docs/adr/0015).

The product photo is the picture: a blurred copy fills the frame, the photo
itself sits on top, and the pair moves slowly under a text layer that does
not — the badge on top and the burned-in subtitle at the bottom stay still so
they can be read. The bottom quarter is left empty on purpose: every vertical
feed lays its own caption and buttons over it.

Narration, Ken Burns, music and the mux are render.py's; only the layout is
new here.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app import render, shop

logger = logging.getLogger(__name__)

W, H, CW, CH = render.W, render.H, render.CW, render.CH
# The photo layer is drawn oversized like render.py's cards; the Ken Burns
# move ends on its centre WxH, which is where the design coordinates live.
DX, DY = (CW - W) // 2, (CH - H) // 2
SIDE = 60
PHOTO_TOP, PHOTO_H = 300, 1080
END_PHOTO_TOP, END_PHOTO_H = 260, 760
BADGE_Y, SUBTITLE_Y = 150, 1440
PRICE_TOP, PRICE_GAP = 1070, 36
ORANGE = (238, 77, 45)
WHITE = (255, 255, 255)
PRICE = (255, 214, 0)
STRUCK = (220, 220, 220)
BADGE_SIZE, SUBTITLE_SIZE = 64, 66
SUBTITLE_SPACING = 1.75


def _photo(path: Path) -> Image.Image:
    # Phone photos carry their rotation in EXIF; Pillow ignores it unless told.
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _contain(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = min(w / img.width, h / img.height)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def photo_layer(path: Path, out: Path, top: int = PHOTO_TOP, box_h: int = PHOTO_H) -> Path:
    """Blurred fill plus the photo itself, on the oversized canvas."""
    photo = _photo(path)
    canvas = _cover(photo, CW, CH).filter(ImageFilter.GaussianBlur(45))
    canvas = Image.blend(canvas, Image.new("RGB", (CW, CH)), 0.35)
    front = _contain(photo, W - 2 * SIDE, box_h)
    mask = Image.new("L", front.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *front.size), 36, fill=255)
    pad = 40
    shadow = Image.new("RGBA", (front.width + 2 * pad, front.height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad, front.width + pad, front.height + pad), 36, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    x = DX + (W - front.width) // 2
    y = DY + top + (box_h - front.height) // 2
    canvas.paste(shadow, (x - pad, y - pad + 12), shadow)
    canvas.paste(front, (x, y), mask)
    canvas.save(out)
    return out


def _pill(draw: ImageDraw.ImageDraw, text: str, y: int, size: int = BADGE_SIZE) -> None:
    font = render._fit([text], render.THAI_BOLD, size, W - 2 * SIDE - 88)
    width = font.getlength(text)
    pad_x, pad_y = 44, 22
    height = font.size + 2 * pad_y + 16
    x0 = (W - width) / 2 - pad_x
    draw.rounded_rectangle((x0, y, x0 + width + 2 * pad_x, y + height), height / 2, fill=ORANGE)
    draw.text((W / 2, y + pad_y + 8), text, font=font, fill=WHITE, anchor="mt")


def _subtitle(draw: ImageDraw.ImageDraw, lines: list[str], y: int) -> None:
    font = render._fit(lines, render.THAI_BOLD, SUBTITLE_SIZE, W - 2 * SIDE)
    for i, line in enumerate(lines):
        draw.text((W / 2, y + i * font.size * SUBTITLE_SPACING), line, font=font, fill=WHITE,
                  anchor="mt", stroke_width=8, stroke_fill=(0, 0, 0))


def text_layer(beat: dict, out: Path) -> Path:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _pill(draw, beat["badge"], BADGE_Y)
    _subtitle(draw, beat["lines"], SUBTITLE_Y)
    img.save(out)
    return out


def end_layer(pitch: dict, out: Path) -> Path:
    """Price and where to buy. Without a price the card is the CTA alone."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _pill(draw, pitch["end_badge"], 120, size=56)
    price, old = pitch.get("price") or "", pitch.get("old_price") or ""
    if price:
        # Stacked by the ink each line really covers, not by fixed offsets:
        # Waree's ascent leaves a lot of air above digits, and the first cut
        # drew the old price straight through the new one (2026-10-13).
        top = PRICE_TOP
        if old:
            off = shop.discount(price, old)
            struck, label = f"฿{old}", (f"  ลด {off}%" if off else "")
            font = render._font(render.THAI_BOLD, 72)
            left, ink_top, _, ink_bottom = draw.textbbox((0, 0), struck + label, font=font)
            width = font.getlength(struck)
            x = (W - font.getlength(struck + label)) / 2
            draw.text((x, top - ink_top), struck, font=font, fill=STRUCK)
            if label:
                draw.text((x + width, top - ink_top), label, font=font, fill=PRICE)
            mid = top + (ink_bottom - ink_top) / 2
            draw.line((x - 6, mid, x + width + 6, mid), fill=STRUCK, width=6)
            top += ink_bottom - ink_top + PRICE_GAP
        big = render._font(render.THAI_BOLD, 170)
        text = f"฿{price}"
        left, ink_top, right, _ = draw.textbbox((0, 0), text, font=big, stroke_width=6)
        draw.text(((W - (right - left)) / 2 - left, top - ink_top), text, font=big,
                  fill=PRICE, stroke_width=6, stroke_fill=(0, 0, 0))
    _pill(draw, pitch.get("cta") or shop.CTA, SUBTITLE_Y, size=60)
    img.save(out)
    return out


def segment(base: Path, text: Path, seconds: float, out: Path, zoom_in: bool) -> Path:
    """The photo moves, the words do not. Video only."""
    frames = max(round(seconds * render.ZOOM_FPS), 2)
    render._run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(base), "-loop", "1", "-i", str(text),
        "-filter_complex",
        f"[0:v]{render.ken_burns(frames, zoom_in)}[bg];"
        "[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
        "-map", "[v]", "-t", f"{seconds:.3f}",
        "-c:v", "libx264", "-threads", "2", "-filter_complex_threads", "2", "-preset", "veryfast", "-crf", "23",
        "-r", str(render.ZOOM_FPS), "-an", str(out),
    ])
    return out


async def build(pitch: dict, photos: list[Path], workdir: Path) -> tuple[Path, dict]:
    """Pitch + photos → mp4, plus what the record keeps about how it was made."""
    workdir.mkdir(parents=True, exist_ok=True)
    beats = pitch["beats"]
    cards = [{"narration": b["narration"], "spoken": b["spoken"]} for b in beats]
    cards.append({"narration": pitch["end_narration"], "spoken": pitch["end_spoken"]})

    audio, starts = await render._narration_track(cards, workdir, voice=shop.VOICE)
    total = render.audio_seconds(audio)
    spans = [
        (starts[i + 1] if i + 1 < len(starts) else total + render.TAIL_PAD) - starts[i]
        for i in range(len(starts))
    ]

    segments = []
    for i, (beat, seconds) in enumerate(zip(beats, spans)):
        base = photo_layer(photos[beat["photo"] - 1], workdir / f"photo{i:02d}.png")
        text = text_layer(beat, workdir / f"text{i:02d}.png")
        segments.append(segment(base, text, seconds, workdir / f"seg{i:02d}.mp4", zoom_in=i % 2 == 0))
    end = len(beats)
    base = photo_layer(photos[0], workdir / "photo-end.png", END_PHOTO_TOP, END_PHOTO_H)
    text = end_layer(pitch, workdir / "text-end.png")
    segments.append(segment(base, text, spans[end], workdir / f"seg{end:02d}.mp4", zoom_in=True))

    silent = render.concat(segments, workdir / "silent.mp4")
    music = render.pick_music()
    clip = render.mux(silent, audio, workdir / "clip.mp4", music)
    details = {
        "seconds": round(render.audio_seconds(clip), 3),
        "frame": [W, H],
        "voice": shop.VOICE,
        "rate": os.environ.get("TTS_RATE", "+0%"),
        "bgm": music.name if music else None,
        "beats": [{"start": round(s, 3), "seconds": round(span, 3)}
                  for s, span in zip(starts, spans)],
    }
    return clip, details


def video_segment(source: Path, text: Path, seconds: float, out: Path, *, fit: str, scene_id: str) -> Path:
    """Trim actual footage to narration; never repeat or freeze its last frame."""
    from app.shop_media import MediaError, probe, run
    info = probe(source)
    if info['type'] != 'video':
        raise MediaError(f'scene {scene_id}: expected video')
    if info['duration'] + .025 < seconds:
        raise MediaError(f'scene {scene_id}: source too short ({info["duration"]:.2f}s; need {seconds:.2f}s)')
    if fit not in {'crop', 'contain'}:
        raise MediaError(f'scene {scene_id}: invalid fit')
    scale = (f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}' if fit == 'crop'
             else f'scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black')
    run(['ffmpeg', '-v', 'error', '-y', '-threads', '2', '-i', str(source), '-loop', '1', '-i', str(text),
         '-filter_complex_threads', '2', '-filter_complex',
         f'[0:v]{scale},setsar=1,fps={render.ZOOM_FPS}[bg];[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]',
         '-map', '[v]', '-t', f'{seconds:.3f}', '-an', '-c:v', 'libx264', '-threads', '2',
         '-preset', 'veryfast', '-crf', '23', str(out)])
    return out


def factual_brief(job: dict) -> str:
    return '\n'.join([job['name'], job['brief'], f"ราคาปัจจุบัน {job['current_price']}",
                      f"ราคาเดิม {job['old_price']}"])


def pitch_from_plan(job: dict) -> dict:
    plan = job['plan']
    references = job['references']
    return {**plan, 'beats': [{**scene, 'photo': references.index(scene['reference_id']) + 1,
                            'spoken': scene.get('spoken') or scene['narration']}
                           for scene in plan['scenes']]}


def canonical_plan(job: dict) -> dict:
    """Use the exact validated values for speech, overlays, prices and captions.

    Validation strips blank lines/whitespace and normalizes currency. Merge those
    values back by position while preserving immutable scene IDs and media keys.
    """
    raw = job['plan']
    if raw.get('studio'):
        # A Studio pack's last scene is the closing line, not a beat (ADR 0018).
        beats_only = {**job, 'plan': {**raw, 'scenes': raw['scenes'][:-1]}}
        clean = shop.validate(pitch_from_plan(beats_only), factual_brief(job), len(job['references']))
        scenes = [{**scene, **beat} for scene, beat in zip(raw['scenes'], clean['beats'])] + raw['scenes'][-1:]
        return {**raw, **clean, 'scenes': scenes}
    clean = shop.validate(pitch_from_plan(job), factual_brief(job), len(job['references']))
    scenes = [{**scene, **beat} for scene, beat in zip(raw['scenes'], clean['beats'])]
    return {**raw, **clean, 'scenes': scenes}


async def build_snapshot(snapshot: dict, media_root: Path, workdir: Path) -> tuple[Path, dict]:
    """Render only the frozen approved snapshot after measuring its TTS."""
    from app.shop_media import MediaError, probe
    plan, assets = canonical_plan(snapshot), snapshot['assets']
    if plan.get('studio'):
        return await _build_studio(plan, assets, media_root, workdir)
    scenes = plan['scenes']
    if not any(scene['source'] in {'flow', 'real'} for scene in scenes):
        raise MediaError('at least one video scene is required')
    workdir.mkdir(parents=True, exist_ok=True)
    cards = [{'narration': s['narration'], 'spoken': s.get('spoken') or s['narration']} for s in scenes]
    cards.append({'narration': plan['end_narration'], 'spoken': plan.get('end_spoken') or plan['end_narration']})
    audio, starts = await render._narration_track(cards, workdir, voice=shop.VOICE)
    total = render.audio_seconds(audio)
    if not math.isfinite(total) or not 0 < total + render.TAIL_PAD <= 60:
        raise MediaError('measured narration plus tail must fit within 60 seconds')
    if len(starts) != len(cards) or any(not math.isfinite(start) for start in starts):
        raise MediaError('invalid measured narration timing')
    spans = [(starts[i + 1] if i + 1 < len(starts) else total + render.TAIL_PAD) - start for i, start in enumerate(starts)]
    if any(not 0 < span <= 60 for span in spans):
        raise MediaError('invalid measured narration scene duration')
    segments = []
    root = media_root.resolve()
    def source_path(asset_id):
        asset = assets.get(asset_id)
        if not asset or asset['validation'] != 'valid':
            raise MediaError('snapshot asset missing or invalid')
        path = (root / 'assets' / asset['key']).resolve()
        if not path.is_relative_to(root):
            raise MediaError('unsafe snapshot asset path')
        return path
    for i, (scene, seconds) in enumerate(zip(scenes, spans)):
        source = source_path(scene['media_id'])
        info = probe(source)
        text = text_layer({'badge': scene.get('badge') or scene.get('purpose') or 'สินค้า', 'lines': scene['lines']}, workdir / f'text{i:02d}.png')
        out = workdir / f'seg{i:02d}.mp4'
        if scene['source'] == 'still':
            if info['type'] != 'image':
                raise MediaError(f'scene {scene["id"]}: expected still image')
            base = photo_layer(source, workdir / f'photo{i:02d}.png')
            segments.append(segment(base, text, seconds, out, zoom_in=i % 2 == 0))
        else:
            segments.append(video_segment(source, text, seconds, out, fit=scene.get('fit', 'crop'), scene_id=scene['id']))
    base = photo_layer(source_path(scenes[0]['reference_id']), workdir / 'photo-end.png', END_PHOTO_TOP, END_PHOTO_H)
    text = end_layer(plan, workdir / 'text-end.png')
    segments.append(segment(base, text, spans[-1], workdir / 'seg-end.mp4', zoom_in=True))
    silent = render.concat(segments, workdir / 'silent.mp4')
    music = render.pick_music()
    clip = render.mux(silent, audio, workdir / 'clip.mp4', music)
    return clip, {'seconds': round(render.audio_seconds(clip), 3), 'frame': [W, H], 'voice': shop.VOICE,
                  'bgm': music.name if music else None,
                  'scenes': [{'id': scene['id'], 'start': round(start, 3), 'seconds': round(span, 3)}
                             for scene, start, span in zip(scenes, starts, spans)]}


async def _build_studio(plan: dict, assets: dict, media_root: Path, workdir: Path) -> tuple[Path, dict]:
    """A Studio job: each scene's cut footage and the character's own voice (ADR 0018)."""
    import asyncio

    from app import shop_studio
    from app.shop_media import MediaError
    root = media_root.resolve()

    def path(asset_id):
        asset = assets.get(asset_id)
        if not asset or asset['validation'] != 'valid':
            raise MediaError('snapshot asset missing or invalid')
        found = (root / 'assets' / asset['key']).resolve()
        if not found.is_relative_to(root):
            raise MediaError('unsafe snapshot asset path')
        return found

    shots = [(scene, path(scene['media_id']), path(scene['voice_id'])) for scene in plan['scenes']]
    return await asyncio.to_thread(shop_studio.build_shots, shots, workdir)
