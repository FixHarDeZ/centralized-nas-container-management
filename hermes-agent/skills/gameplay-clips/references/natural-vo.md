# Natural VO: `scripts/gen_vo_natural.py` (edge-tts or Gemini TTS)

Fix's complaint (2026-11-05): the gameplay VO "ยังไม่ธรรมชาติมาก". Root causes in the old
`gen_vo_custom.py` output: written-Thai script, one rate/pitch for every phrase, identical
0.4 s gaps (metronome). `gen_vo_natural.py` fixes all three; plan.json schema in its docstring.
A/B demo sent 2026-11-05 (LEGO Batman, msg 6244 = edge, 6245 = Gemini).
**Fix's call: B (Gemini) is the default. A (edge) is the fallback only when Gemini hits its limit.**

## Run rules from SKILL.md step 7 (moved 2026-11-12, read every run)
- บทเป็น **ภาษาพูด** (นะ/เลย/อะ/สุดๆ, ตัดภาษาโฆษณา), ตัวเลขใน `say` เป็นคำ, ใน `sub` เป็นเลขได้; gap ไม่เท่ากัน (0.22 ในเรื่องเดียว, 0.30–0.50 เปลี่ยนเรื่อง); ≥4 gaps >0.25 วิ ต่อ 20 วิ
- **plan.json ต้องมี edge `rate/pitch` ต่อวลีด้วยเสมอ** — Gemini ฟรี 10 req/วัน/โมเดล, หมดทุกโมเดลสคริปต์ fallback เป็น **เสียง A (edge Premwadee, hook `+5%/+15Hz`, body `-2..+3%/+11..+14Hz`, CTA `-6%/+9Hz`)** เอง → stdout `engine used: edge` = ใส่ warm EQ chain (pitfall "เสียงเหมือน AI") และแจ้งฟิกใน delivery ว่าใช้เสียง A เพราะติด limit
- **จำนวนวลี + ช่วงที่ยอมรับของ `vo_end`**: ต้องจบในช่วง `DUR−3 … DUR−1.6` (20 วิ = 17.0–18.4 วิ) — สั้นกว่านั้นทิ้งหางดนตรีเปล่าท้ายคลิปเกิน 3 วิ, เกินนั้นซับล้นเฟรมสุดท้าย. Gemini พูดบทไทยได้ 10–16 อักขระ/วิ ต่อวลี แล้วแต่ take → **อย่าเชื่อสูตร "กี่วลี = กี่วิ"**: เขียน 5–6 วลี รัน แล้วแก้จาก stdout `vo_end` เท่านั้น. จบช้า → รัน `--from-take <take.wav>` (0 request) ตามลำดับใน pitfall «ฟิต VO เข้าเดดไลน์»; จบเร็ว/หางดนตรีเปล่าเกิน → เพิ่มประโยค (ต้อง gen take ใหม่ = กินโควตา)
- **โควตา 2.5 หมดได้เร็ว** → สคริปต์ไล่ไป 3.8 เอง (stdout `engine used: gemini`); ดู stdout ทุกครั้ง
- **ASR ทุก take ก่อน build** (Gemini อาจอ่านคำสั่งออกเสียง/เติมคำ) — **ต้องเป็น ASR ภาษาไทย**: `uv run --with faster-whisper --with numpy python <skill_dir>/scripts/asr_th.py vo.mp3` (raw array path, `language='th'`) แล้วเทียบทีละวลีกับบท. **`scripts/asr_speech_spans.py` hardcode `language="en"`** → รันกับ vo.mp3 ได้ขยะ (คำไทยถูกถอดเป็น ASCII ซ้ำ ๆ ทุกบรรทัด) ห้ามใช้ตรวจ VO; เช็คคำลงท้ายด้วยหู/whisper medium (whisper small หลอนคำลงท้ายไทย)
- **เส้นตาย VO**: `end ≤ DUR − 1.5` และจบก่อนเซกการ์ดท้ายที่มีเสียงประกาศ ≥0.3 วิ; Gemini พูดช้ากว่า → ใช้ `max_inner_pause` + `tempo ≤1.07`, เกินนั้น **ตัดคำ** อย่าเร่ง
- เก็บ raw take ไว้ (`--take-out`) → จูน gap/ตัดใหม่ด้วย `--from-take` ไม่เสียโควตา
- ถ้ามี REF clip ของฟิก: ส่ง 2 โทน (`+30Hz` = A ที่ฟิกเลือกกับ REF, `+50Hz`) ตาม `references/audio-reference-matching.md`

## Default run (B with automatic A fallback)
```
uv run --with edge-tts --with faster-whisper --with numpy python <skill_dir>/scripts/gen_vo_natural.py plan.json
```
- Write the plan with `"engine": "gemini"`, `"voice": "Leda"`, `"style": "cheerful, casual, like telling a friend"`.
  Give every phrase `say/sub/mood/gap_after` **plus** edge `rate/pitch`; the fallback needs them.
- The model chain `3.8-flash → 3.1-flash-preview → 3.8-flash-lite → 2.5-flash` moves to the next model
  ONLY on a daily-quota 429. Per-minute 429s are retried. When every model is exhausted it falls back
  to edge automatically.
  - stdout prints `engine used: …`, which is also written to `vo.engine`.
  - If it is `edge`: apply the warm EQ chain, and tell Fix in the delivery that the clip used voice A
    because of the limit.
- `tempo`/`max_inner_pause` apply to Gemini only. The fallback ignores them.
- Test the fallback without spending quota: set `VO_GEMINI_CHAIN=<already-exhausted models>`.
  Verified 2026-11-05: falls back to edge, 6 events.

## Script writing (both engines; biggest win)
- Spoken Thai, not ad copy: particles (นะ / เลย / อะ / สุดๆ), cut "มาพร้อมกับ / สัมผัสประสบการณ์".
  e.g. "เปิดโลกก็อตแธมเล่นได้อิสระเต็มที่" -> "โลกก็อตแธมเปิดกว้าง จะไปตรงไหนก็ได้เลยอะ".
- Numbers as words in `say` ("เจ็ดตัว"), digits allowed in `sub` ("7 ตัว").
- Uneven gaps: 0.22 s inside one idea, 0.30–0.50 s between ideas/topics.

## edge engine
Per-phrase prosody: hook `+5% / +15Hz`, body `-2..+3% / +11..+14Hz`, CTA `-6% / +9Hz`.
Apply the warm EQ chain from SKILL.md pitfalls ("เสียงเหมือน AI") to `vo.mp3` afterwards, level-matched.

## Gemini engine (key `GEMINI_API_KEY` in /opt/data/.env)
- **Run the script with no env prefix.** It loads the key from `/opt/data/.env` itself. Do not `source` the file in the shell: that command is held for approval and stalls the run (see SKILL.md pitfalls).
- **Free tier = 10 requests / DAY / model** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
  checked on 2.5-flash and 3.8-flash). The default mode is therefore `"mode": "whole"`: ONE request for
  the whole script, then the take is split into phrases by faster-whisper word timestamps plus the
  quietest 20 ms point. Measured boundaries match ASR segments within 0.1–0.25 s.
  Never use per-phrase mode (`"mode": "phrase"`) on the free tier: it burns 6 requests per clip.
- The raw take is saved (`--take-out`). Re-time or re-gap with `--from-take` at **0 requests**.
- Fallback models when one is 429: `gemini-3.8-flash-tts` → `gemini-3.1-flash-tts-preview` →
  `gemini-3.8-flash-lite-tts` → `gemini-2.5-flash-preview-tts`. Each has its own 10/day.
- **Prompt form is model-specific (ASR-verified):**
  - **3.x models READ prose directions aloud.** This applies to a Thai instruction block, "Say …:" and
    "Read aloud …:" alike, and produced 13–19 s takes for a 2 s line. Use the tag form `[cheerful, casual] <script>`.
  - 2.5 obeys `Read aloud in a <how> tone:\n<text>`.
  - 3.8 + tag on a single phrase improvised an extra "โอ้โห". The whole-script call followed the script
    exactly. **Always ASR the take before building.**
- Gemini speaks slower and breathes more: the same 6 lines took 20.0 s raw vs 15.6 s on edge. Fit a
  deadline with `max_inner_pause` (0.18) and `tempo` (≤1.07). Cut words before going above 1.07, or it
  sounds rushed again.
- An intermittent candidate comes back with `finishReason` but no `content`. The script retries it.
- Voices tried: Leda (used), Laomedeia, Zephyr, Aoede. Female, youthful.
- **CTA phrase must start inside the last seg — solve the gap from one run's numbers, don't nudge-and-rerun.** The `Link below!` line is spoken in the final seg only; `build_v5 --check` gates the CTA *pill*, so it stays green while the VO CTA straddles the cut. From one stdout you have `prev_end` (end of the phrase before the CTA) and `cta_dur = vo_end − cta_start`; `--check` prints the last seg's `t0`. The gap window is `last_seg_t0 − prev_end ≤ gap_after ≤ (DUR − 1.6) − prev_end − cta_dur` (CTA start = prev_end + gap, measured exact). Take the middle of the window, re-time ONCE with `--from-take` (0 requests), confirm both numbers. `--check` only prints OK/LATE at `DUR − 1.5` — looser than the window top, so it can bless a gap that eats the music tail. Window empty (CTA line too long for seg boundary → deadline) = shorten the wording; no gap fixes that.
- Gap ladder example (20 s, 5 phrases at ~14 ch/s): lead 0.10 + gaps 0.35–0.40 gave `vo_end` 15.9 s. Re-timing the same take with lead 0.25 + gaps 0.65 via `--from-take` gave 17.1 s at 0 requests. Adjust gaps before writing extra phrases, since each new phrase costs a request.

## Gates (same as SKILL.md)
- `sub_linecheck.py` passed for both demos.
- VO end must be ≤ (end-card start − 0.3 s). The LEGO end card starts at 18.70 s; Gemini VO ended 18.36 s.
- ASR (whisper small) of the final Gemini VO heard the ending as "นะครับ", while the raw take ASR said
  "นะคะ". Whisper small hallucinates Thai particles, so check endings **by ear or with whisper medium**
  before shipping.
