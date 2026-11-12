# Presenter post-production: `scripts/post_presenter.py` (our own EN pills + Thai subs)

Goal: Flow renders with NO on-screen text, then we burn our own EN pills and Thai libass subs.
Thai subs are timed from Flow's own voiceover. This removes the garbled Flow Thai text for good.
Demo (Giffarine raw scenes, which still carry Flow's own text because it was a timing test):
`/opt/data/cache/scratch/presenter-post-test/out.mp4`, sent to Fix on 2026-11-05 (msg 6263).
**Fix approved it on 2026-11-05 ("รีวิวแล้วเอาตามนี้เลย"). It is now the default presenter path.**

## Run
```
uv run --with faster-whisper --with numpy --with pillow --with pythainlp \
    python <skill>/scripts/post_presenter.py plan.json [--workdir DIR] [--sheet]
```
The plan schema is in the docstring: scenes[{video, prompt|script, pills}], xfade, seam_whoosh,
model, trim. The script text comes from the prompt's `Audio (Thai voiceover): "..."` line.
Outputs: `subs.ass`, `pills.txt`, `out.mp4` (mastered, FB-safe High/yuv420p, faststart),
`report.json`.

- **A run that dies printing NOTHING (no traceback, only a leaked-semaphore warning) is an OOM kill**, not an
  empty failure: the container is cgroup-fenced at 4 GB. Cause on 2026-11-12: `auto` loaded whisper medium
  while small was still cached (~3.6 GB). Fixed in the script since (one model in RAM, measured peak 1.95 GB
  for small → medium), so `"model": "auto"` is safe again. If it still gets killed, run with
  `CT2_CPU_THREADS=2 OMP_NUM_THREADS=2` and `"model": "small"`. Heavy scripts take one shared lock
  (`heavylock.py`): exit 75 `BUSY: …` = another one is running, rerun later. Peak RAM per run is in
  `/opt/data/clips/logs/heavy-log.jsonl`.

- **Silent H / B-roll shots:** set `"silent": true` on the scene and leave out `script`/`prompt`. It gets no ASR and no subs, only pills, and still joins the xfade and the timeline. Without the flag, an empty script crashes the align step.
- **No CTA pill:** run with `NO_AUTO_CTA=1` when Fix moved the CTA to the caption, or on a heavy-content clip. Otherwise the script auto-adds `Link below!` over the last 2.2 s, and it collides with a pill you placed there (`pills overlap` exit).
- **graphics_layer image_stickers:** the avoid-check box is `w_est+42` wide. Keep `x - (w_est+42)/2` past the face box's right edge, or the run exits with `covers avoid-zone 'face'` and leaves the OLD `final.mp4` in place. Check that the sha changed.

## Run gate (read before any send)
- A run prints `FLAG:` lines and writes `report.json`. Read both before sending. `FLAG: ... not in script` means Flow's voiceover spoke words the script does not contain: the burned subs still follow the script, so the audio can be wrong while the subs look right. Report it to Fix with the frame time, and let him choose between delivering as-is and regenerating that scene — UNLESS the flagged fragments are the script's OWN words out of order (signature: CER far above the ~0.2 norm, `match=0/N`, and a mid-script phrase timestamped at the scene's start): that is Flow speaking the script REORDERED to fit the visual beat order, not ad-libbing. Confirm with an unprompted probe of the raw scene; when every script phrase appears exactly once, reorder `plan.json`'s script to the spoken order and re-run — 0 credits, and the alignment then passes so the subs follow the real audio. Only words genuinely absent from the script go to Fix as deliver-as-is/regenerate.
- **Not every FLAG is a defect.** `clipjob.py deliver` matches flags against `INFO_FLAGS` (anything containing `auto-added`, e.g. the auto `Link below!` pill) and ships without an `--ack`. Only real defects — words not in script, a skipped phrase, `pause_err` max well past ~1.5 s — need Fix's call passed as `--ack "<flag>=<his call>"`. Never stall a finished clip waiting for him to ratify an auto-added pill.
- A `phrases_matched` count below total, or an `onset_err` over ~1 s, means the subs may lag the audio. Check it before delivery, not after.
- The run can yield to background in the terminal. Poll it to exit before reading its output; never send `final.mp4` while the run is still writing.

## Measured accuracy (2 scenes, 17 phrases)
- **ASR whisper `small` with the script as `initial_prompt`:** CER 0.015 / 0.038. Without the
  prompt it is 0.28 / 0.14, so prompting is what makes it work.
- **Phrases matched:** 17/17. No inserted words flagged.
- **Boundary error vs `silencedetect` pauses:** −0.16…+0.27 s, mostly ≤0.13 s. Subs appear and
  disappear on the right words.
- **Head-freeze trim:** 0.167 s detected on scene 1, 0 on scene 2. a_dur == v_dur (19.583).
- **Master:** I −14.6 LUFS, max −4.3 dB.
- **sub_linecheck:** 1 "FAIL" on event 8 (`ลิงก์อยู่ใต้คลิปนะ\Nไปดูกันได้เลย`). It is a false fail:
  the two lines' marks touch (1 px gaps), so the band counter merges them. A crop-zoom vision check
  confirmed 2 clean lines. **Verdict: timing is good enough to adopt** once Fix OKs the look.

## Prompt block for Flow (paste into every presenter scene, replaces any caption instructions)
```
ON-SCREEN TEXT: NONE. No captions, no subtitles, no titles, no labels, no logos, no watermark,
no stickers, no emoji, no cartoon graphics, no hand icons, no pointing-hand graphics, no arrows, no floating text of any language anywhere in the frame for the whole clip. (Flow still drew a cartoon pointing-hand overlay when only "no stickers, no emoji" was written, so name the graphic types explicitly.)
ห้ามมีตัวอักษรใดๆ บนจอตลอดทั้งคลิป (ไม่มีซับ ไม่มีป้าย ไม่มีโลโก้) — ข้อความทั้งหมดจะใส่ทีหลังเอง
Audio (Thai voiceover): "<exact Thai lines>"  — พูดตามนี้ทุกคำ ไม่เพิ่ม ไม่ตัด ห้ามพูดประโยคใดซ้ำสอง พูดจบแล้วเงียบจนจบคลิป เหลือแค่เสียงดนตรี
```
Keep each spoken line short with natural breaks between ideas (each break becomes a subtitle event), but the WHOLE script must still fill the scene — see the repetition rule below.

## Looped voiceover: a short script makes Flow repeat the last phrase (2026-11-06)
Flow stretches the voiceover to fill the scene's full duration. When the script runs out early it does **not** go quiet — it says the last phrase again, or stutters one word to pad. Measured on the KENZZO kids-wardrobe clip, both scenes, unprompted ASR of the raw renders:
- scene 1 (script ≈4.3 s of speech in a 10 s scene): `ห้องรกแค่ไหน` 0–2 s, `ดูก่อนกับหลังใช้ตัวนี้` 2–5 s, then **the same phrase again 5–7 s**.
- scene 2: `ลิ้นชักมีกุญแจ` **`ล็อกได้ ล็อกได้`** — one word doubled to pad.
Two causes, both preventable:
1. **Fill the duration.** Thai presenter pace is ~3.5–4.5 syllables/s, so a 10 s scene needs roughly 30–38 syllables (usually 3 phrases), i.e. speech covering **≥70 % of the scene**. Count the script's syllables, divide by 4, compare with the scene length BEFORE submitting; if it falls short, add a จุดเด่น line rather than letting the model improvise. A genuinely short line belongs in a shorter generation (Omni offers 4/6/8 s), not in a padded 10 s scene.
2. **Write the anti-repeat clause verbatim** — the `Audio (Thai voiceover)` line above. A bare `Audio (Thai voiceover): "..."` with no clause is what shipped the looped clip.

### Detection gate — run it on every raw scene BEFORE stitching
**Never clear a scene on `post_presenter.py`'s prompted CER.** The script is fed to whisper as `initial_prompt`, which snaps the transcript onto the script and HID a whole repeated phrase: scene 1 reported `CER=0.0`, `match=2/2`, no FLAG, while repeating `ดูก่อนกับหลังใช้ตัวนี้` for 2 s. Instead transcribe each raw scene **unprompted with `vad_filter=False`** and read the segment list: any script phrase appearing twice, or speech continuing past the last script phrase, is a repetition defect → re-gen that scene (Fix's call, it costs credits) or report it with the frame check.
Latent signal in the existing report, worth reading every run: `pause_errors` far from zero with no FLAG means silencedetect found speech where the script-aligned ASR had none. Scene 1's `max=4.844 s` was exactly that — treat `pause_err` max above ~1.5 s as "suspected repeat, run the unprompted probe".
`silencedetect` alone cannot find it: Flow lays a continuous music bed, so `-38dB:d=0.25` returns NO silence rows at all on these renders and the speech span is invisible.
### Zero-credit repair when a looped clip already exists (Fix's call 2026-11-06: *"ตัดคลิปช่วงที่พูดซ้ำไปเลย"*)
A re-gen is NOT the only remedy — the repeat can be removed from the delivered file for 0 credits. **Cutting the span out of video AND audio beat muting it**, and is what Fix chose:
- Get the exact span from **word-level** unprompted ASR (`word_timestamps=True`): the repeat's first and last word give the window, and the gaps on either side give the margin to cut in. Convert scene-local → final time with the report's `trim_s` and `global_start` (`final = global_start + raw - trim_s`).
- Snap both edges to frame boundaries (post output is 24 fps) and keep the cut INSIDE the surrounding silence — a cut 7 ms early clips the real phrase's tail.
- One pass, no segment files: `trim`/`atrim` + `setpts`/`asetpts` per kept segment → `concat=n=N:v=1:a=1`, with a 10 ms `afade` at each join (inaudible, and short enough not to swallow a phoneme). **The FB-safe output flags are mandatory here — this is a multi-segment stitch** (`-pix_fmt yuv420p -profile:v high -level 4.0` + bt709 tags), then `verify-clip.py`.
- **Cutting can FIX subtitle sync as a side effect:** the burned subs travel with their own frames, so removing the frames that carried an early-starting caption pulls that caption onto its spoken line. On the KENZZO clip the CTA sub went from 0.85 s early to 0.013 s early with no re-burn. Check the kept spans of every pill too — a pill showing on BOTH sides of the cut stays continuous, so it does not flicker.
- Prove it: unprompted ASR of the CUT file must show the script once, and sample one frame each side of every join (subs/pills complete, no half-drawn glyphs).
- Cost it honestly in the delivery: the clip gets SHORTER than the ordered duration (19.71 → 16.71 s) and each cut is a visible jump cut.
- **When the repeated phrase IS the closing CTA, the auto-cut takes the CTA with it.** `detect_repeats.py --cut` removes the whole repeated run (both copies), so the delivered clip ends without a link line. Decide with Fix first (keep one copy, drop both, or re-gen): a one-copy cut needs word-level timestamps of the run, and the midpoint of the run is NOT the boundary between copies — two attempts at 8.30 s and 8.66 s both left a clipped copy. Verify any hand cut by unprompted ASR of the result, not by timestamps.
- **A CTA-less final scene needs the script trimmed to match.** The burned subs follow `Audio (Thai voiceover)`, so keep the script identical to the audio that survives the cut (use a `prompt_sN_cut.txt` beside the raw scene), otherwise post_presenter flags the dropped phrase as `not heard`.
- **post_presenter auto-adds a `Link below!` pill to the final scene** whenever none is planned. For a CTA-less clip set `NO_AUTO_CTA=1` in the environment (the script honours it), or the pill lands on the last seconds anyway.
The mute-and-patch alternative (kept for when a cut would break a gesture): voice and music share ONE track, so muting leaves a hole in the music — splice music-only audio from a speech-free span of the same scene over the repeat instead, with ~30 ms crossfades, via stdlib `wave` + numpy, then remux `-c:v copy`.

**uv-env pitfall for the probe:** in an ephemeral `uv run --with faster-whisper --with numpy` env, `WhisperModel.transcribe(<path>)` dies with `TypeError: open() got an unexpected keyword argument 'metadata_errors'` (PyAV/faster-whisper mismatch) — which reads as a broken model. Decode the wav yourself and pass the array: `ffmpeg -i scene.mp4 -ac 1 -ar 16000 s.wav`, then stdlib `wave` → `np.frombuffer(raw, np.int16).astype(np.float32)/32768.0` → `m.transcribe(audio, language='th', vad_filter=False)`. Run one ASR job at a time (RAM).

## Two-scene recipe (the delivered build)
1. Raw scenes copied into one workdir as `scene1_raw.mp4`, `scene2_raw.mp4`, with the matching `prompt_s1.txt` / `prompt_s2.txt` next to them (the Audio line is the script).
2. `plan.json`: `scenes[{video, prompt, pills}]`, `xfade: 0.25`, `seam_whoosh: true`, `model: auto`, `trim: auto`. Pill `start`/`end` are scene-LOCAL seconds, EN only, ≤2 words, and the `Link below!` pill goes only on the last scene.
3. Run it with `--workdir` and `--out` both set. Read the per-scene line: `match=N/N`, `pause_err max` under ~1 s, and `CER` (unprompted ASR CER of ~0.17–0.20 on Thai is normal; judge repetition by the unprompted probe, not by CER).
4. `out.mp4` is the candidate. Check three frames (~4.5 s, mid, last 1 s) for subs and pills, then `verify-clip.py` on that exact file.

### Chaining scene 2 (verified 2026-11-08)
- Scene 2's start frame can be the ONLY chip. Extract it from scene 1's raw render: `ffmpeg -y -v error -sseof -0.15 -i scene1_raw.mp4 -frames:v 1 lastframe.jpg`, upload it, attach it, and leave out the character chip, since the frame already shows the presenter. Dropping the character chip also removes one refusal trigger (see the prominent-person pitfall).
- Prompt for scene 2: `Start exactly on the attached last-frame image`, plus `CONTINUITY:` naming the same face, outfit and backdrop. Scene 2 is the only scene that carries the CTA.
- `plan.json` can set `"script"` directly instead of `"prompt"`, which avoids keeping separate prompt files in sync with the plan.
- Re-run post_presenter after every plan change (script or pill edits). A run takes a few minutes, so do not read `out.mp4` until the run exits.

## Pitfalls
- **Plan the total length before you read the output.** Final duration ≈ Σ(scene seconds) − (N−1)·xfade − Σtrim. Five 4 s scenes with xfade 0.25 and small head-trims came out 18.4 s, not 20. To hit the ordered length, use `xfade: 0` (hard cuts, the seam whoosh still plays) or give the sum enough headroom, and state the real length in the delivery.
- **A pill longer than 2 words aborts the whole run** (`pill … has >2 words`) and leaves the previous out.mp4 in place. Check the sha changed after every run. Write pills as 1–2 words before the run starts.
- **Flow may speak words the script does not contain** (an ad-lib interjection at the start of a scene). post_presenter reports it as `FLAG: … not in script` and burns no subtitle for it, so the viewer hears a word the subs never show. Decide per clip with Fix: deliver as-is or regenerate that scene. Do not silently cut it.
- **Kill Chrome before the post run.** `post_presenter` (whisper + ffmpeg) exited 137 (OOM) while the Flow browser was still resident on the NAS (~8.4 GB used of 11.9 GB). Close Chrome once generation and downloads are finished, then run the post step alone.
- **Check the delivered file, not the scratch copy.** `verify-clip.py` flags a file byte-identical to its own Downloads original as a duplicate. Run verify on the Downloads path itself (the `ok:true` verdict carries `sent_from`), not on a copy in scratch.
- **Always pass the known script as whisper `initial_prompt`.** Unprompted Thai ASR misspells brand
  names (Gifferin, เอาคลาย), and 2/17 phrases then fall back to proportional timing.
- **A pill/sub check reads the rendered frame, not the prompt.** A single late-frame vision read missed both pills in an earlier run; sample each pill's own time (see SKILL.md step 8).
- **Use `small`, not `medium`.** Medium gained nothing measurable here, and its RAM use contributed
  to the 2026-11-05 OOM that killed the gateway. Run ASR jobs one at a time.
- **Pills like `2-Stage Filter` / `2-Year Warranty`** count the hyphenated token as one word
  (≤2 words OK), but they are still digits. Keep them clearly spec, never money-like.
- **Sub look = Itim 48 pastel-yellow `&H0066D1FF`, dark-brown outline `&H00203050` Outline 5 Shadow 2.5, `BorderStyle=1` (no box)** — the style line in `post_presenter.py` and the `gen_vo_*.py` scripts. Never reintroduce the black box: it reads as a news caption and hides the product held at chest height.
- **Burn subs with `ass=<file>:fontsdir=<dir>:shaping=complex`.** This ffmpeg build defaults libass to simple shaping, which drops stacked tone marks onto the upper vowel (ขึ้น renders as "ขึน"); `subtitles=` has no `shaping` option. Verify by bbox: rendering `ขึ้` must be taller than `ขึ` (complex: +24 px at 140pt; simple: ~+2).
- **Subs use MarginV 465** (safe-zones.md). Presenter faces must sit at y≈250–800 so the text
  doesn't cover the face; check it in the frame check.
- **`sub_linecheck` counts fill pixels only (`LIT=120`)** so the dark outline cannot bridge two lines into
  one band. If it still reports 1 band for a 2-line event, the marks really touch — confirm with a crop
  zoom before "fixing" anything.

## Changing the subtitle look (when Fix complains about it)
1. Find a clean frame (no burned subs) from the last delivered clip, with the product visible:
   `ffmpeg -ss T -i clip.mp4 -frames:v 1 f_T.png` at several T → one vision sheet, pick the clean one.
2. Write one tiny `.ass` per variant (same header as the scripts, only the `Style:` line changes, a real
   phrase with stacked marks such as `…คล่องขึ้น`), burn each with `ass=…:shaping=complex`, plus the
   current style as "เดิม" for comparison. Label and tile them with PIL into one jpg.
3. Vision-check a 2x zoom of the text band (glyphs, contrast against the product) before sending.
4. Send the sheet with Bot API `sendPhoto` (token via `send_clip.read_token()`), then ask with `clarify`
   buttons: colour variant + position (MarginV 465 is the lowest point clear of app UI; the next option
   up covers the face).
5. Apply the pick to every `Style:` line (post_presenter + gen_vo_natural/custom/subs) with an exact
   string replace + count assert, rerun `sub_linecheck.py` on a 1-line + 2-line test ass, `py_compile`.
