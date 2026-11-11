# Footage sourcing and speech-gap detection (gameplay / footage clips)

Use this when picking the source video and the silent windows for a footage clip. The SKILL.md step 2 rules still apply; this file is the method.

## 0. Speech table from auto-subs — the step 2 rules (moved from SKILL.md 2026-11-12)
- ดึง body ต้องกินทั้งบรรทัด header (timestamp + `align:start position:0%`) ไม่งั้น `align/start/position` หลุดเข้า text แล้ว cue เปล่าทุกใบนับเป็นเสียงพูด → ช่วงว่างหายทั้งไฟล์
- cue ที่มี tag `<c>` = word timestamp ใน tag คือ ground truth; auto-subs ซ้อน cue (repeat ข้อความก่อน) → strip tag + merge/dedupe ก่อนหา gap
- cue มีแต่ `[music]` = ช่วงว่าง, มี `>>` = เสียงพูด. เพลงที่มีเนื้อร้องตลอดแต่ไม่มี `>>` = เพลง ให้ duck จัดการ ใช้ได้ทุกช่วง. cue เดียว `[music]` คลุมทั้งเรื่อง = ไม่มีเสียงพูด เลือกได้ทุกช่วง
- **ทุก seg ต้องอยู่ในช่วงว่าง** (อังกฤษใต้พากย์ไทย = สองภาษาทับกัน ข้อห้ามแรก; การ์ดท้ายที่ประกาศชื่อเกมเป็นข้อยกเว้นเดียว เพราะ VO จบก่อนแล้ว). เว้นขอบ ≥0.1 วิ จากเสียงพูด
- **อย่าเชื่อ gap จาก VTT ล้วนกับ trailer ยาว/reveal**: auto-subs มักไม่มี cue ช่วงต้นหรือช่วงบทในเกม (เห็นเป็นช่วงว่างหลายสิบวิทั้งที่มีบทพูด) → ยืนยันด้วย ASR (faster-whisper small, `vad_filter=False`) บนเสียงช่วงที่จะใช้ แล้วเขียน speech VTT จาก ASR ให้ build_v5 ใช้เป็น `vtt`. วิธีเต็มใน `references/footage-sourcing.md`
- trailer บางเรื่องไม่มี auto-subs → เช็ค `--list-subs` ก่อนโหลด; **ซับโหลดติด `HTTP 429` = rate limit ของ YouTube → retry ครั้งเดียวแล้วพอ ข้ามไป ASR ตรง ๆ** (ASR คือ ground truth อยู่แล้ว); มีหลายตัว → โหลดเฉพาะซับทุกตัว (`--skip-download`) นับช่วงว่าง ≥1.5 วิ แล้วเลือกตัวที่ช่วงว่างพอ plan คลิป
- ผลรวม seg ≥ DUR; **ใช้ trailer เรื่องเดียวทั้งคลิป** (คนละเรื่อง = เพลงกระโดดที่ seam); จำเป็นจริงใช้เรื่องที่สองเฉพาะเซกท้ายแล้วบอกใน delivery

## 1. Getting the source
- Default: `uv tool run yt-dlp -f '299+ba/bv*[height<=1080]+ba' --merge-output-format mp4 -o <name>.mp4 <url>`.
- `Sign in to confirm your age` (age-gated trailers, common on violent titles): retry with `--extractor-args 'youtube:player_client=tv_embedded'`. This client needs no cookies and returns the 1080p mp4 formats. Check with `--list-formats` first.
- Subtitle fetch with the same client: `--write-auto-subs --sub-langs en --sub-format vtt --skip-download -o <prefix>`. Use a literal prefix; do not use `%(ext)s` templates inside shell strings.
- **YouTube's subtitle endpoint rate-limits with `HTTP 429` and stays blocked across retries** — burn at most one retry, then drop subs and go straight to ASR (§3): the gap map comes from ASR anyway, and the plan's `vtt` is written from ASR spans, so auto-subs were only ever a shortcut.
- Run yt-dlp through `execute_code`/`subprocess` with an explicit `cwd`; the persistent terminal shell can get stuck on a stale cwd and fail every command (every command dies with the same `cd: <old dir>` line — pass `workdir=` on the next call to reset it).

## 2. Choosing the source video
- **Rank candidates by measured speech-free seconds, not by length — ASR first, sheets after.** Run `asr_speech_spans.py` on each candidate (`--start 0 --dur <full>`) *before* building any contact sheet, sum the gaps from the JSON, and pick the source with the most gap seconds. Length alone inverts: a 17-minute presenter-commentary preview held ~11 s of usable window while a 2.5-minute sparse-narration clip held ~28 s, and the sheets built on the long one were wasted work.
- The script's stdout only lists gaps ≥1.5 s; for short-gap sources recompute every gap ≥0.6 s yourself from the `<src>_asr.json` spans (`cur → next start`), because a 20 s plan is often assembled from 2 s gaps.
- **Commentary signature:** dense back-to-back ~2 s ASR segments whose English reads fluent-but-nonsensical = foreign-language commentary whisper rendered as English (not music hallucination). It still counts as speech — those windows are unusable either way, and the density tells you the source is talk-heavy before you sheet it.
- Developer-talk segments are full-frame talking heads. Never use them as footage.
- Cinematic cutscenes are NOT gameplay. Check every candidate window with a contact sheet before choosing it.
- **แต่ cinematic / trailer ใช้ได้เมื่อ gameplay หาไม่ได้ (ฟิกสั่ง 2026-11-07)** — ถ้า ASR + contact sheet สรุปแล้วว่าไม่มีฟุตเทจเกมเพลย์ที่ใช้ได้ (มีแต่คนพากย์, ช่วงสะอาดสั้นกว่าที่สั่ง, หรือ gameplay ไม่ปรากฏใน source ใดเลย) ให้เลือกช็อตจาก cinematic cutscene / trailer ทางการต่อทันที แล้วรายงานใน delivery ว่าเป็น cinematic ไม่ใช่ gameplay — อย่าย่อความยาวหรือรอถามฟิกเพียงเพราะ "ไม่ใช่เกมเพลย์"
- Verdict questions for vision (ask in one line, per tile): is there a HUD/health bar, an active weapon swing, enemy hit VFX, or a player-controlled camera? Cinematic tiles show composed close-ups, reaction beats, slow establishing shots and talking mouths. Vision has called cinematic footage "combat" when the figures were only gesturing; a window passes only if the action is visible in the tiles, not inferred.
- Title cards, PEGI/publisher cards and end cards are not usable for Shopee (other-platform logos).
- **Count the usable seconds before committing to a duration.** A window is usable only if it is speech-free AND text-free (no pills, disclaimers, title/date cards, HUD prompts that read as text) AND free of logos. Visual-novel dialogue boxes count as text — a source whose quiet windows all sit on dialogue scenes yields ~0 usable seconds no matter how long it is. Sum the usable windows. If the sum is below the ordered duration, do not stretch footage, do not hold frames, and do not ship text-overlay frames: give Fix the options (shorter clip at the usable length, a different source, or footage he supplies) and wait for his pick. Short release-date trailers often yield only ~10–15 s of clean footage.

### 2a. Feasibility gate — run BEFORE the master encode and the ASR pass
Spending the encode and ASR time on a source that cannot reach DUR wastes the run. Do this first, on tiles only (cheap):
1. Contact sheets at 1 fps over the whole trailer (40 tiles per sheet, from the 16:9 source, not the master crop).
2. Bottom-strip subtitle montage over the candidate gameplay tiles (§5b). Mark each tile: gameplay / cinematic / card, and subtitle yes/no.
3. Count the seconds that are gameplay (or allowed cinematic) AND subtitle-free AND card/logo-free. Merge adjacent tiles into runs.
4. Total < DUR → stop and send Fix the options via `clarify` (shorter clip at the real total / graphic-only build / footage he supplies). Do not encode or run ASR until he answers. A run that cannot reach DUR must not spend the encode, the ASR or the VO.

Measured on a 2:50 PS5 gameplay trailer: vision tiles gave roughly 5–8 s of gameplay with no subtitle, no card and no speech. The ASR-based gap list (~30 s opening) overstated this: the opening held logo/ESRB cards and cutscenes with on-screen subtitles that ASR did not catch.

## 3. Speech gaps: do not trust the auto-subs alone
- **Look up a video by its direct `watch`/`youtu.be` URL, never by a YouTube search-results URL** — `--list-formats` on a `results?search_query=` page hung past 120 s with no output. Get the video ID from a web search hit first.
- yt-dlp auto-subs can omit whole stretches, especially in-game dialogue. A VTT that starts at 3 min while the video speaks from 0 s gives false "silent" gaps. The VTT's first cue time is a quick sanity check against the audio.
- Ground truth: ASR over the candidate range with faster-whisper, raw-array path (ffmpeg decode to `f32le` 16 kHz mono, `np.frombuffer`, then `WhisperModel("small", device="cpu", compute_type="int8").transcribe(arr, language="en", vad_filter=False, beam_size=1)`). Offset the segment times by the ffmpeg `-ss`.
  - Run: `uv run --with faster-whisper --with numpy python <script>.py`. Measured cost: about 1 min of CPU per 3 min of audio with the small model.
  - Whisper can hallucinate on music-only audio ("Thank you for watching"). A one-word hit with no frame evidence is noise — and a hit at a perfectly round, evenly spaced time (0 / 30 / 60 / 90 s) is the same artifact: do not carve those windows out of your gap list, or you lose usable seconds to a ghost.
- One command does the ASR, the padded speech spans, the WEBVTT and the gap list: `uv run --with faster-whisper --with numpy python <skill>/scripts/asr_speech_spans.py SRC.mp4 --start S --dur D --rebase S --out-json asr.json --out-vtt speech.vtt`. Use `--rebase S` when the master was encoded with `-ss S`, so the VTT already matches the master timeline.
- **No-speech source (a game with no voiced dialogue, no subs):** skip ASR. Write `subs.en.vtt` as the header only (`WEBVTT`); `build_v5 --check` then treats the whole timeline as one gap. Still run the on-screen-text checks (§5), because in-game dialogue boxes and menus are text, not speech.
- Speech spans are padded ~0.1 s each side and written as a WEBVTT (`HH:MM:SS.mmm --> HH:MM:SS.mmm align:start position:0%` + one text line per span). `build_v5.py` `vtt_gaps` treats any cue with letters as speech, so this file works as the `vtt` key.
- Gap for a seg = from the end of one span + margin to the start of the next span - margin. Keep each seg audio fully inside one gap.
- **ASR under-reports dialogue on story trailers.** A 170 s English-narrated trailer came back with 9 speech spans and a 30 s "silent" opening, while the contact sheets showed subtitled dialogue in most gameplay tiles. ASR gives the AUDIO gate only. The TEXT gate (subtitles, nameplates, HUD text) must come from the bottom-strip subtitle montage in §5(b) — never from ASR gaps alone. When the two disagree, the lower usable total wins.

## 4. Timeline bookkeeping (build_v5)
- `build_v5` measures gaps against the `master` file's own timeline. If you encode only a window with `-ss S`, the master starts at 0 = S: shift every speech span by -S in the VTT and every seg `in`/`audio_in` by -S.
- A `hero` seg takes its picture from the 1080p `trailer` (absolute time) but its audio gate from `audio_src: master` + `audio_in` (relative). Keep the two numbers separate.
- Encoding the source window directly as master with `-ss S -t D` is the default; the speech VTT from ASR on the full source must then be shifted with `scripts/rebase_vtt.py speech.vtt S subs.en.vtt` (drops cues ending before S, keeps the header format `build_v5` parses).
- Encoding the full 20+ min source to master takes ~8 min on the NAS. Encode only the window you need (`-t` = window end) and rebase the times.

## 5. Contact sheets (cheap, no credits)
- Window tiles: `ffmpeg -ss T -t D -i master.mp4 -vf "crop=720:405:0:320,fps=N,scale=240:135,tile=CxR" -frames:v 1 sheet.png` with `N = C*R/D` so the grid covers the range.
- **The `crop=720:405:0:320` band is `master.mp4`-only** (720×1280 pad, picture at y=320). A raw 1920×1080 source must be tiled with no crop (or a correct center crop) — reusing the master's crop on it yields a squished top-left strip and garbage classifications; `crop=iw:iw*9/16:0:0` is NOT a 9:16 crop (that is a 3.2:1 band). Sheet the file you will actually cut from, and regenerate a sheet whose geometry is wrong rather than reading it.
- **Seeking with `-ss` before `-i` resets the timestamp label to 0.** A sheet cut from `-ss 1050` labels its tiles 0…1050 s relative to the cut, and vision then reads them as if they were real times. Add the offset in the label itself: `drawtext=text='%{eif\:t+1050\:d}'`. Otherwise keep a separate offset note for every sheet.
- **Long source (20+ min): tile the window you plan to cut, not the whole file.** One 6×6 sheet at 30 s/tile covers 18 minutes. Split the file into 18-minute ranges and label each sheet with its absolute offset.
- Tile index → time: `t = start + (i-1) / fps`, with `fps = C*R/D` as above. Write the time next to every tile label before reading the sheet; a 48-tile sheet over 36 s gives 0.75 s per tile, and a label off by one tile moves a cut by a whole gap-margin.
- One sheet per candidate window; 30-48 tiles reads reliably. Ask vision for index + 3-5 words per tile, then pick the run.
- Pick the hero from the tiles with the most readable action and no text overlay; check the hero's 9:16 crop on the 1080p source, not the master.
- **Vision sheets mislabel: verify two things by pixels, not by the label.** (a) Static vs moving: take 3 frames 0.5 s apart and compare with `ImageChops.difference` mean; a moving gameplay camera gives a large mean, a title/logo/ESRB card gives ~0. Vision called static cards "gameplay" on a trailer sheet. (b) Dialogue/subtitle presence: build one montage of the bottom 34% of each candidate frame (`crop=iw:ih*0.34:0:ih*0.66`, scaled to a small tile) and ask one question for the whole montage: "any dialogue box, subtitle, or large text? yes/no per tile". A full-frame read misses subtitles; the bottom strip shows them.
- **Keep sheets to about 30–40 tiles per call.** At 60+ tiles the per-tile indices drift and the labels stop matching the timestamps. Split a long window into several sheets, and ask for 'label + 4 words' only.
- **Use the vision answer as a candidate list, then confirm the winners with the two pixel checks above** before cutting.

## 5c. Pixel checks before cutting (cheap, do them every time)
- **Dark-dip scan.** Per-frame luma of the master, bucketed to 0.5 s; any bucket under ~25 YAVG is a cut or fade to black. Command: `ffmpeg -v info -i master.mp4 -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=yavg.txt" -an -f null -`, then average YAVG per 0.5 s from `pts_time:` / `YAVG=` lines in that file. Keep every window and every hero's in→out inside runs above the threshold. A hero that starts at a black cut shows an empty first frame on the cold open — the most visible defect in the clip. Measured on one NVIDIA promo: dips at 9 s, 24 s and 38 s, and the first 5 s was a title card.
- **Corner-overlay check.** Read the four corners of 3–4 frames at full resolution (a 1920×1080 frame cropped to each 400-px corner, one vision call for all four). Publisher/hardware FPS, DLSS or RTX panels live in the top-right and bottom-right corners and are not HUD. Crop them out in the master encode (keep the crop x below the panel's left edge), not in the hero.
- **Sanity-check the master's black pad.** The master is 720×1280 with the picture at y 320..725, so a whole-frame mean includes black bars. Judge brightness only inside the picture band (crop y 330..680), otherwise every frame looks dimmer than it is.

## 5d. Whole-source OCR text map — run it BEFORE locking segs
- Contact-sheet vision cannot answer "is there text in this window": it returns a paragraph instead of the requested per-tile lines, repeats one string across tiles that never contained it, and misses a legal micro-caption ~18 px tall at 1080p. A fixed-bbox bright-pixel probe is not a substitute either — dark/gold product art inside the probe box counts as "bright" and false-positives as text.
- Objective alternative: OCR every frame at 1 fps and keep `{t: [{text, box}]}` as JSON.
  ```
  uv run --with rapidocr-onnxruntime --with numpy --with pillow python ocr_scan.py
  # loop: ffmpeg -ss T -i src.mp4 -frames:v 1 -update 1 f_T.jpg  ->  RapidOCR()(f_T.jpg)
  ```
  `rapidocr-onnxruntime` lands in an ephemeral uv env (nothing installed on the host), about 1 s per frame.
- Read the map, not the pictures: contamination falls out as a time range (legal micro-caption, date/availability card), while text printed ON the product (device logos, cartridge-slot labels, HUD) appears the same way — keep those, drop only supers. Place every seg in/out outside the supers, then re-run OCR at the planned in points as the final check.
- OCR still misses low-contrast or heavily stylised titles, so keep the contact-sheet pass for cards and logos; OCR is the gate for small body text and for anything whose presence you would otherwise be guessing.

## 6. Load and CPU limits on the NAS
- Keep only one heavy job (ASR, encode, build) running at a time; ASR plus ffmpeg encode together left about 600 MB free and swap full during one run.
- Run long jobs with `subprocess.Popen` writing to a log file, then poll the log in short sleeps.
- **A foreground `terminal` call hard-caps around 420 s no matter what `timeout` you ask for** — an ASR/encode longer than that returns `timed out` with no output and kills the job. Launch it as `terminal(background=true)` writing to an output file, then poll for the file in short foreground calls; a wait-loop inside one foreground call outruns the cap and loses its own tail output.
