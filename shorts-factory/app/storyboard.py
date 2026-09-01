"""Storyboards: English prompts the human pastes into Google Flow.

Flow has no "storyboard" screen. What it has is *Ingredients to Video* (up to
three reference images per prompt) and *Frames to Video*, so a storyboard here
is really two things: one prompt that makes the master character image, and one
prompt per scene that names that same character again. Everything the images
are generated from is English — Flow's image model is prompted in English —
while everything the human reads is Thai.

The bot stops at the prompts. It does not generate images and does not assemble
video (docs/adr/0006).
"""
from __future__ import annotations

import logging
import os
import re

from app.script import ScriptError, _client, _parse, _say

logger = logging.getLogger(__name__)

DEFAULT_SCENES = 4
MIN_SCENES, MAX_SCENES = 2, 8
SHORTS_RATIO, LONG_RATIO = "9:16", "16:9"
BUDGET_SECONDS = float(os.environ.get("STORYBOARD_TIMEOUT_SECONDS", "300"))

THAI = re.compile(r"[ก-๙]")
# Every image prompt has to carry these or the frames come back with burnt-in
# captions and split panels, which are useless as Flow ingredients.
NEGATIVES = "no text, no watermark, no UI, no split-screen"

SYSTEM_PROMPT = """You are an expert storyboard artist and short-form video director.
Convert the brief into a cohesive storyboard with strict visual consistency, to be
generated in Google Flow.

RULES:

1. MASTER CHARACTER LOCK
   - If the story needs a person, define exactly ONE fictional master character with
     concrete physical attributes (age, ethnicity, hair, glasses/accessories, clothing
     colours and style) and write `locked_prompt_tag`: one English noun phrase naming
     all of it, e.g. "the same 28-year-old Asian man with short textured hair, thin
     black eyeglasses, and a light blue rolled-up oxford shirt".
   - Every scene's `image_gen_prompt` MUST contain that `locked_prompt_tag` word for
     word, or the character changes face between scenes.
   - If the story needs no person, set `master_character` to null and keep the visual
     style identical across scenes instead.
   - Never reference real people, celebrities, brands or news events.

2. IMAGE PROMPTS (`image_gen_prompt`)
   - English only. One single photorealistic frame — never a collage, comic strip or
     multi-panel grid.
   - Must state the aspect ratio {ratio}.
   - Must end with: {negatives}
   - {layout}

3. MOTION (`motion`)
   - One English clause describing camera movement and the action over ~8 seconds,
     e.g. "slow push in as he looks up from the laptop". No audio, no dialogue.

4. THAI FIELDS
   - `scene_description`, `visual_details`, `scene_mood_note` and the overview fields
     are written in Thai, for the human reading them.
   - {script_rule}

5. Output valid JSON only, exactly this shape:
{{
  "overview": {{
    "title": "...",
    "mood_tone_progression": "...",
    "target_audience": "...",
    "master_character": {{
      "name": "...", "age": 28, "ethnicity": "...",
      "appearance": "...", "outfit": "...", "locked_prompt_tag": "..."
    }}
  }},
  "scenes": [
    {{"scene_number": 1, "camera": "...", "scene_description": "...",
      "visual_details": "...", "sound_verbatim": "...", "on_screen_text": "...",
      "scene_mood_note": "...", "image_gen_prompt": "...", "motion": "..."}}
  ]
}}"""

SHORTS_LAYOUT = ("Leave clean negative space in the centre of the frame for Thai "
                 "subtitles: `clean center composition for text overlay`.")
LONG_LAYOUT = "Compose for a wide screen; no subtitle safe area is needed."
SHORTS_SCRIPT_RULE = ("The scenes are given below and are fixed: keep the same number "
                      "of scenes, in the same order. Copy each scene's narration into "
                      "`sound_verbatim` and its on-screen lines into `on_screen_text` "
                      "word for word — never rewrite them.")
LONG_SCRIPT_RULE = ("Write `sound_verbatim` yourself as the Thai voiceover of that "
                    "scene, and leave `on_screen_text` empty unless a caption is part "
                    "of the story. Default to 4 scenes; if the brief asks for another "
                    "number, follow the brief.")

SCENE_FIELDS = ("camera", "scene_description", "visual_details", "scene_mood_note",
                "image_gen_prompt", "motion")


def _system(ratio: str, shorts: bool) -> str:
    return SYSTEM_PROMPT.format(
        ratio=ratio,
        negatives=NEGATIVES,
        layout=SHORTS_LAYOUT if shorts else LONG_LAYOUT,
        script_rule=SHORTS_SCRIPT_RULE if shorts else LONG_SCRIPT_RULE,
    )


def _brief_from_script(script: dict) -> str:
    """The Script, laid out as the brief for its own storyboard."""
    parts = [f"หัวข้อคลิป: {script['title']}", ""]
    for i, card in enumerate(script["cards"], 1):
        parts += [
            f"ฉากที่ {i}",
            f"  narration (ใส่ใน sound_verbatim คำต่อคำ): {card['narration']}",
            f"  ข้อความบนจอ (ใส่ใน on_screen_text คำต่อคำ): {' '.join(card['lines'])}",
            f"  ภาพที่คิดไว้คร่าวๆ: {card.get('query', '-')}",
        ]
    return "\n".join(parts)


def validate(data: dict, ratio: str, scenes_wanted: int | None = None) -> dict:
    """Reject a storyboard that would send the human to Flow with holes in it."""
    overview = data.get("overview")
    if not isinstance(overview, dict):
        raise ScriptError("ไม่มี overview")
    for key in ("title", "mood_tone_progression", "target_audience"):
        if not str(overview.get(key) or "").strip():
            raise ScriptError(f"overview: ไม่มี {key}")

    scenes = data.get("scenes")
    if not isinstance(scenes, list):
        raise ScriptError("scenes ต้องเป็น list")
    if scenes_wanted is not None and len(scenes) != scenes_wanted:
        raise ScriptError(f"ต้องมี {scenes_wanted} ฉากให้ตรงกับสคริปต์ แต่ได้ {len(scenes)}")
    if not MIN_SCENES <= len(scenes) <= MAX_SCENES:
        raise ScriptError(f"ต้องมี {MIN_SCENES}-{MAX_SCENES} ฉาก แต่ได้ {len(scenes)}")

    character = overview.get("master_character") or None
    tag = str((character or {}).get("locked_prompt_tag") or "").strip()
    if character and not tag:
        raise ScriptError("master_character: ไม่มี locked_prompt_tag")

    for i, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ScriptError(f"ฉากที่ {i}: ไม่ใช่ object")
        for key in SCENE_FIELDS:
            if not str(scene.get(key) or "").strip():
                raise ScriptError(f"ฉากที่ {i}: ไม่มี {key}")
        prompt = scene["image_gen_prompt"]
        # Flow's image model is prompted in English; Thai in here comes back as
        # a frame that ignored half the instruction.
        if THAI.search(prompt) or THAI.search(scene["motion"]):
            raise ScriptError(f"ฉากที่ {i}: image_gen_prompt/motion ต้องเป็นภาษาอังกฤษล้วน")
        # The lock is the whole point of a master character: a paraphrase in one
        # scene is a different face in that scene.
        if tag and tag.lower() not in prompt.lower():
            raise ScriptError(
                f"ฉากที่ {i}: image_gen_prompt ต้องมี locked_prompt_tag คำต่อคำ"
            )
        if ratio not in prompt:
            raise ScriptError(f"ฉากที่ {i}: image_gen_prompt ต้องระบุอัตราส่วน {ratio}")
        if "no text" not in prompt.lower():
            raise ScriptError(f"ฉากที่ {i}: image_gen_prompt ต้องมี \"{NEGATIVES}\"")
        scene["scene_number"] = i
    data["ratio"] = ratio
    return data


def lock_to_script(data: dict, cards: list[dict]) -> dict:
    """Force the words back onto the storyboard rather than trusting the copy.

    The narration and the on-screen lines are already decided — they are what
    the renderer will speak and draw — so they are written in here instead of
    being validated. A storyboard whose SOUND drifted from the clip is a set of
    images made for a video that does not exist.
    """
    for scene, card in zip(data["scenes"], cards):
        scene["sound_verbatim"] = card["narration"]
        scene["on_screen_text"] = " ".join(card["lines"])
    return data


async def plan(brief: str, ratio: str, cards: list[dict] | None = None) -> dict:
    """A brief (or a Script) → a validated storyboard. One retry, told what broke."""
    messages = [{"role": "system", "content": _system(ratio, shorts=cards is not None)},
                {"role": "user", "content": brief}]
    client = _client()
    wanted = len(cards) if cards else None
    last: Exception | None = None
    for attempt in range(2):
        raw = await _say(client, messages, temperature=0.8, budget=BUDGET_SECONDS)
        try:
            data = validate(_parse(raw), ratio, wanted)
            return lock_to_script(data, cards) if cards else data
        except ScriptError as exc:
            logger.warning("storyboard ผิดกติกา: %s", exc)
            last = exc
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"ผิดกติกา: {exc} — ส่ง JSON ใหม่ให้ถูกกติกา"},
            ]
    raise ScriptError(str(last))


async def for_script(script: dict) -> dict:
    """The 9:16 storyboard for a Script that is waiting for review."""
    return await plan(_brief_from_script(script), SHORTS_RATIO, cards=script["cards"])


async def for_brief(brief: str) -> dict:
    """The 16:9 storyboard for a long-form video, from a one-line brief."""
    return await plan(brief, LONG_RATIO)


def character_message(data: dict) -> dict | None:
    """The prompt that makes the master character image, or None if there is no
    character to lock — that image is the ingredient every scene refers to."""
    overview = data["overview"]
    character = overview.get("master_character") or None
    if not character:
        return None
    tag = character["locked_prompt_tag"]
    return {
        "heading": (
            f"🎭 ตัวละครหลัก: {character.get('name', '-')} "
            f"({character.get('age', '-')} ปี)\n"
            "สร้างภาพนี้ใน Flow ก่อน แล้วใช้เป็น ingredient ของทุกฉาก "
            "(ไม่งั้นหน้าคนเปลี่ยนทุกฉาก)"
        ),
        "blocks": [(
            "ภาพตัวละคร",
            f"A photorealistic {data['ratio']} portrait of {tag}, neutral studio "
            f"lighting, plain background, full body visible, {NEGATIVES}",
        )],
    }


def scene_messages(data: dict) -> list[dict]:
    """One message per scene: what to read in Thai, what to paste in English."""
    out = []
    for scene in data["scenes"]:
        heading = "\n".join(filter(None, [
            f"🎬 ฉาก {scene['scene_number']}/{len(data['scenes'])} · {scene['camera']}",
            f"📖 {scene['scene_description']}",
            f"👁 {scene['visual_details']}",
            f"🔊 {scene['sound_verbatim']}",
            f"📝 ข้อความบนจอ: {scene['on_screen_text']}" if scene.get("on_screen_text") else "",
            f"🎯 {scene['scene_mood_note']}",
        ]))
        out.append({
            "heading": heading,
            "blocks": [
                ("ภาพ (Nano Banana / Frames)", scene["image_gen_prompt"]),
                ("วิดีโอ (Ingredients to Video)",
                 f"{scene['image_gen_prompt']}, {scene['motion']}"),
            ],
        })
    return out


def messages(data: dict) -> list[dict]:
    """Everything to send, in the order it is used: overview, character, scenes."""
    overview = data["overview"]
    head = {
        "heading": "\n".join([
            f"📋 storyboard: {overview['title']} ({data['ratio']}, {len(data['scenes'])} ฉาก)",
            f"🎞 โทน: {overview['mood_tone_progression']}",
            f"🎯 คนดู: {overview['target_audience']}",
        ]),
        "blocks": [],
    }
    character = character_message(data)
    return [head] + ([character] if character else []) + scene_messages(data)
