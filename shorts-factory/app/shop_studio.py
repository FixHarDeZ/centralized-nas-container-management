"""Shop Studio packs: a Product Clip made the 🎞 Studio pack way (docs/adr/0018).

Every shot is a Flow shot and the character says its line on camera (ADR
0017), holding or using the product, which comes into Flow as an Ingredient
(`@Product`, an Asset Profile made from the Brief's photos). There is no end
card: the closing line is the last shot. This module is the part both front
ends share: the Telegram /shop Brief and, later, the Creator Studio job.
"""
from __future__ import annotations

import re
from pathlib import Path

from app import render, shop, shop_render, storyboard, studio
from app.shop_media import probe

MAX_LINES = 2
PRODUCT_RULE = (
    "The shots are given below and are fixed: write exactly one scene per shot, in the same "
    "order and the same number. Every shot is one continuous take. "
    f"`{storyboard.PRODUCT_TAG}` is the product in the attached reference photos: write it as "
    f"`{storyboard.PRODUCT_TAG}` in every image_gen_prompt, with the character holding, using or "
    "showing it the way the line describes. Never describe its shape, colour, packaging text, "
    "logo or brand, and never change or add to it: the photos are the product. No other "
    "products, no price tags, no on-screen text. Leave `sound_verbatim` and `on_screen_text` "
    "empty; they are filled in from the script. Also give the overview a `title_en` (the clip's "
    "title in English, 2-6 words) and a `product_en` (a short generic English name for the "
    "product, e.g. \"wireless earbuds\", no brand).")
# The Pitch is written as a woman ("ค่ะ"); a character the model invents must match.
WOMAN = "ตัวละครหลักต้องเป็นผู้หญิง (บทพูดลงท้าย ค่ะ)"
SPOKEN_RULE = ("ไทยล้วน ห้ามมีอักษรละติน ห้าม ฿ (เขียน บาท) ตัวเลขคงเป็นตัวเลขอารบิกเหมือน narration "
               "ห้ามเขียนเป็นคำ (ห้าม สองร้อย)")


def shots(pitch: dict) -> list[dict]:
    """One shot per beat, then the closing line as a shot of its own."""
    out = [{"badge": b.get("badge") or "", "lines": list(b["lines"]), "narration": b["narration"],
            "spoken": b["spoken"], "photo": b.get("photo") or 1} for b in pitch["beats"]]
    out.append({"badge": pitch.get("end_badge") or "", "lines": lines_for(pitch["end_narration"]),
                "narration": pitch["end_narration"], "spoken": pitch["end_spoken"],
                "photo": out[0]["photo"] if out else 1})
    return out


def script_for(pitch: dict) -> dict:
    """The Pitch shaped like a Script, so the pack machinery can carry it."""
    return {"title": pitch["title"], "cards": shots(pitch)}


def lines_for(narration: str) -> list[str]:
    """The subtitle for a line: its words exactly, broken where it has to be."""
    return shop.fit_lines([narration])


def condense_check(brief: str):
    """Shop's own rules for a shortened line (ADR 0015), for script.condense()."""
    def check(narration: str, spoken: str) -> list[str]:
        problems = []
        try:
            shop._check_voice(narration, spoken, "บทใหม่", brief)
        except shop.PitchError as exc:
            problems.append(str(exc))
        lines = lines_for(narration)
        if len(lines) > MAX_LINES or any(shop.line_too_wide(line) for line in lines):
            problems.append("ซับยาวเกิน 2 บรรทัด ต้องสั้นกว่านี้")
        return problems
    return check


def apply_condensed(card: dict, text: dict) -> None:
    card.update(text, lines=lines_for(text["narration"]))


def _brief(script: dict, product: dict) -> str:
    parts = [f"สินค้า (ข้อมูลจากผู้ขาย ใช้เฉพาะเข้าใจว่าสินค้าคืออะไร): {product['text'][:800]}", "",
             f"ชื่อคลิป: {script['title']}", ""]
    for i, card in enumerate(script["cards"], 1):
        parts += [f"shot {i}: ตัวละครพูดว่า: {card['narration']}",
                  f"  (รูปสินค้าที่เกี่ยวข้อง: รูป {card.get('photo', 1)})"]
    return "\n".join(parts)


NEGATIVE_START = re.compile(r",?\s*\bno text\b", re.I)


def _with_product(prompt: str) -> str:
    """Name @Product in a prompt that lost it, ahead of the negatives."""
    clause = f", holding {storyboard.PRODUCT_TAG} clearly in view"
    found = NEGATIVE_START.search(prompt)
    if not found:
        return prompt.rstrip(" .,") + clause
    return prompt[:found.start()].rstrip(" .,") + clause + prompt[found.start():]


def _finish(script: dict):
    def finish(data: dict) -> dict:
        for i, (scene, card) in enumerate(zip(data["scenes"], script["cards"]), 1):
            # `@product` is the same tag in other clothes: fixed, not refused.
            prompt = re.sub(re.escape(storyboard.PRODUCT_TAG), storyboard.PRODUCT_TAG,
                            scene["image_gen_prompt"], flags=re.I)
            if storyboard.PRODUCT_TAG not in prompt:
                # A scene that forgot the product gets it put in, not refused: on
                # a live @Kim plan (2026-10-20) a refusal burnt the last attempt.
                prompt = _with_product(prompt)
            scene["image_gen_prompt"] = prompt
            scene["card"] = i - 1
            # Dialogue is what the voice says: Thai script, digits, "บาท".
            scene["sound_verbatim"] = card["spoken"]
            scene["on_screen_text"] = " ".join(card["lines"])
            scene["photo"] = card.get("photo", 1)
        return data
    return finish


async def plan(script: dict, product: dict, choice: str, character: str = "",
               fixed_tag: str = "") -> dict:
    """One scene per shot, the character speaking with `@Product` in hand."""
    brief = _brief(script, product)
    if choice == storyboard.AUTO:
        brief += f"\n\n{WOMAN}"
    count = len(script["cards"])
    return await storyboard.plan(
        brief, storyboard.SHORTS_RATIO, cards=script["cards"], choice=choice, character=character,
        scenes_wanted=count, max_scenes=storyboard.STUDIO_MAX_SHOTS, fixed_tag=fixed_tag,
        script_rule=PRODUCT_RULE + storyboard.STUDIO_SPEAK_RULE, finish=_finish(script),
        # Thai fields the model sometimes skips; the pack never shows them.
        overview_defaults={"title": script["title"], "mood_tone_progression": "-",
                           "target_audience": "-"},
        attempts=3)


def product_name(board: dict) -> str:
    name = str(board["overview"].get("product_en") or "").strip().rstrip(".")
    return name if name and not storyboard.THAI.search(name) else "the product"


def copy_refs(clip_id: str, photos: list[str]) -> list[str]:
    """The Brief's photos beside the pack: the dashboard mounts /data only."""
    refs = studio.root(clip_id) / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    names = []
    for i, photo in enumerate(photos, 1):
        source = Path(photo)
        name = f"photo{i}{source.suffix.lower() or '.jpg'}"
        if source.is_file():
            (refs / name).write_bytes(source.read_bytes())
            names.append(name)
    return names


FRAME_SLACK = 0.03  # under video_segment's 25 ms tolerance plus one rounding step


def _trim(piece: Path, seconds: float, out: Path) -> Path:
    render._run(["ffmpeg", "-y", "-i", str(piece), "-t", f"{seconds:.3f}",
                 "-ac", "1", "-ar", str(studio.VOICE_RATE), "-c:a", "pcm_s16le", str(out)])
    return out


def build(script: dict, clip_id: str, workdir: Path) -> tuple[Path, dict]:
    """The Telegram pack's render: its cut footage and voices under /data/studio."""
    for i in range(len(script["cards"])):
        if not studio.segment_path(clip_id, i).is_file() or not studio.voice_path(clip_id, i).is_file():
            raise RuntimeError(f"shot {i + 1}: ไม่มี footage หรือเสียง — ส่ง export ใหม่")
    return build_shots([(card, studio.segment_path(clip_id, i), studio.voice_path(clip_id, i))
                        for i, card in enumerate(script["cards"])], workdir)


def build_shots(shots: list[tuple[dict, Path, Path]], workdir: Path) -> tuple[Path, dict]:
    """(card, footage, voice) per shot → mp4. Blocking: run off the loop.

    shop_render's video path, the same one the Creator Studio render uses:
    badge on top, subtitle at ~75 %, clear of the mouth. Each segment is as
    long as its trimmed voice; no TTS, no end card, music ducked under.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    pieces, segments, timing, clock = [], [], [], 0.0
    for i, (card, footage, voice) in enumerate(shots):
        piece = studio.voice_piece(voice, workdir / f"v{i:02d}.wav")
        seconds = render.audio_seconds(piece)
        # A line that runs to the very end of its shot has no tail to trim, and
        # the re-encoded footage can be a frame short of the cut window (more
        # so after ✂️ cut evenly): the shorter of the two sets the length.
        room = probe(footage)["duration"] - FRAME_SLACK
        if seconds > room:
            seconds = room
            piece = _trim(piece, seconds, workdir / f"v{i:02d}-cut.wav")
        text = shop_render.text_layer({"badge": card.get("badge") or "สินค้า", "lines": card["lines"]},
                                      workdir / f"text{i:02d}.png")
        segments.append(shop_render.video_segment(footage, text, seconds, workdir / f"seg{i:02d}.mp4",
                                                  fit="crop", scene_id=f"shot-{i + 1}"))
        pieces.append(piece)
        timing.append({"shot": i + 1, "start": round(clock, 3), "seconds": round(seconds, 3)})
        clock += seconds
    audio = render.concat_audio(pieces, workdir / "voice.wav")
    silent = render.concat(segments, workdir / "silent.mp4")
    music = render.pick_music()
    clip = render.mux(silent, audio, workdir / "clip.mp4", music)
    return clip, {"mode": "studio", "seconds": round(render.audio_seconds(clip), 3),
                  "frame": [shop_render.W, shop_render.H], "bgm": music.name if music else None,
                  "shots": timing}


# --- for the Creator Studio worker, which has no /data/studio to write -------

async def measure(script: dict, workdir: Path) -> list[float]:
    """Each shot's span in one take of the shop voice, as the bot measures it."""
    workdir.mkdir(parents=True, exist_ok=True)
    audio, starts = await render._narration_track(script["cards"], workdir, voice=shop.VOICE)
    return studio.spans(starts, render.audio_seconds(audio), render.TAIL_PAD)


async def fit(script: dict, spans: list[float], brief: str, workdir: Path) -> tuple[list[float], list[int]]:
    """Shorten lines a 10s shot would cut off, re-measuring, two rounds at most.

    main.fit_speech() without Telegram. Raises like condense() does; the
    caller decides whether the old lines may stand.
    """
    from app import script as script_gen
    done: list[int] = []
    for round_ in range(2):
        over = [c for c, span in enumerate(spans) if studio.speak_too_long(span)]
        if not over:
            break
        cards = script["cards"]
        targets = {c: studio.speech_budget(script_gen.speech_units(cards[c]["spoken"]), spans[c])
                   for c in over}
        shorter = await script_gen.condense(cards, targets, "th", spoken_rule=SPOKEN_RULE,
                                            check=condense_check(brief))
        for c, text in shorter.items():
            apply_condensed(cards[c], text)
        spans = await measure(script, workdir / f"fit{round_}")
        done += [c for c in shorter if c not in done]
    return spans, done


def studio_plan(pitch: dict, script: dict, spans: list[float], board: dict, tag: str,
                profile: dict | None, references: list[str]) -> dict:
    """A Creator Studio plan: the Pitch plus one Flow scene per shot and the pack."""
    product = product_name(board)
    seconds = {i: studio.speak_seconds(span) for i, span in enumerate(spans)}
    scenes = []
    for i, (card, scene) in enumerate(zip(script["cards"], board["scenes"])):
        photo = min(max(int(card.get("photo") or 1), 1), len(references))
        scenes.append({
            "id": f"scene-{i + 1}", "source": "flow", "fit": "crop", "required_duration": 0,
            "reference_id": references[photo - 1], "photo": photo,
            "badge": card.get("badge") or "", "lines": card["lines"], "narration": card["narration"],
            "spoken": card["spoken"], "purpose": f"shot {i + 1}", "span": round(spans[i], 2),
            "seconds": seconds[i], "flow_prompt": storyboard.animate_prompt(scene, "Thai"),
        })
    markdown = storyboard.studio_markdown(board, tag, {"language": "Thai", "seconds": seconds}, product)
    length = sum(seconds.values())
    beats = [{k: c[k] for k in ("badge", "lines", "narration", "spoken", "photo")}
             for c in script["cards"][:-1]]
    return {**pitch, "beats": beats, "scenes": scenes,
            "studio": {"markdown": markdown, "product": product, "product_tag": storyboard.PRODUCT_TAG,
                       "tag": tag, "character": profile, "length": length,
                       "credits": studio.credits({i: 1 for i in seconds}, seconds)}}
