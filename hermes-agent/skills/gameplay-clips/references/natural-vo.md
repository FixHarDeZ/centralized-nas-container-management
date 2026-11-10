# Natural VO: `scripts/gen_vo_natural.py` (edge-tts or Gemini TTS)

Fix's complaint (2026-11-05): the gameplay VO "ยังไม่ธรรมชาติมาก". Root causes in the old
`gen_vo_custom.py` output: written-Thai script, one rate/pitch for every phrase, identical
0.4 s gaps (metronome). `gen_vo_natural.py` fixes all three; plan.json schema in its docstring.
A/B demo sent 2026-11-05 (LEGO Batman, msg 6244 = edge, 6245 = Gemini).
**Fix's call: B (Gemini) is the default. A (edge) is the fallback only when Gemini hits its limit.**

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
- Gap ladder example (20 s, 5 phrases at ~14 ch/s): lead 0.10 + gaps 0.35–0.40 gave `vo_end` 15.9 s. Re-timing the same take with lead 0.25 + gaps 0.65 via `--from-take` gave 17.1 s at 0 requests. Adjust gaps before writing extra phrases, since each new phrase costs a request.

## Gates (same as SKILL.md)
- `sub_linecheck.py` passed for both demos.
- VO end must be ≤ (end-card start − 0.3 s). The LEGO end card starts at 18.70 s; Gemini VO ended 18.36 s.
- ASR (whisper small) of the final Gemini VO heard the ending as "นะครับ", while the raw take ASR said
  "นะคะ". Whisper small hallucinates Thai particles, so check endings **by ear or with whisper medium**
  before shipping.
