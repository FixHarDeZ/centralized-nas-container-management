# Studio pack Flow Cards can let the character speak

Status: accepted (2026-10-19). Amends 0016 for packs with 🗣 on.

## Context

ADR 0016 makes the edge-tts take the timing master: Flow footage is cut silent
(`-an`) and the take is laid over it. The owner wants the character in the
Flow shots to say the line on camera instead, with its own voice and lips.

A test on a real six-shot Storyboard Studio export (2026-10-19, `@IU`, Thai
dialogue in the prompt) measured:

- The export is 48.000 s, h264 + AAC: Scenes exports carry the generated audio.
- The voice is steady across shots (median pitch 195–211 Hz in every shot).
- Veo speaks 15–25 % slower than the take. 8 s shots held takes of 5.7 and
  6.3 s; takes of 7.1–7.9 s ran into the next shot with no silence at the cut.
- Intelligibility and lip sync are the owner's call by ear, not measured here.

Google documents dialogue as fully supported in English only; other languages
"may work".

## Decision

A per-pack toggle, 🗣, off by default:

- Only 🎬 Flow Cards speak. 🖼 Pexels Cards keep the take. The owner accepted
  the voice switch this causes in a mixed clip.
- One shot per speaking Card: 8 s when its take is ≤ 6.3 s, otherwise 10 s.
  Longer than that is ✂️'s job. Thai has no word boundaries, so a line is never
  split across shots on a guess.
- The dialogue is written into `script.md` and the per-shot prompt from the
  Script after validation. The model's prompts stay English-only.
- The cut keeps each speaking Card's audio. The render splices it into the
  take in place of that Card's slice, keeping its head for lip sync and
  trimming only its tail, so the take still drives every Card's start, the
  subtitles and the music ducking.
- A speaking Card's caption sits under the chin, not across the face
  (`render.draw_card(low=True)`, from `render_studio`'s set of Cards that
  brought a voice). Footage Cards lost the frame-wide scrim at the same time;
  the outline on the text carries legibility instead.

## Consequences

- A silent export of a speaking pack is refused.
- `/say` and the pronunciation checklist do not affect speaking Cards.
- Credits for 10 s shots are not measured; the pack shows a lower bound.
- Speaking clips are `flow-studio` footage and stay out of the hook experiment
  (ADR 0004), as in 0016.
