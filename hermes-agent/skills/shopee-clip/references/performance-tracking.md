# Performance tracking — which hooks/styles actually sell

Why: hook rotation by LRU alone cannot tell a winning opener from a dead one. Real
views/clicks/orders turn rotation into selection. Applies to every style (presenter,
gameplay, broll, …).

## Data
- `/opt/data/clips/logs/perf-log.jsonl` — append-only, one row per stats reading, joined to
  `/opt/data/clips/logs/clip-log.jsonl` by `sha256`. Never write perf numbers into clip-log rows
  (clip-log is the append-only record of what shipped; rewriting it breaks audits).
- Latest reading per clip+platform wins; platforms are summed in reports.

## Commands (`scripts/perf.py`, stdlib only, run with `python3`)
- Record: `perf.py add --match "<product words | sha256 prefix>" --views N --clicks N --orders N [--platform shopee|reels|tiktok] [--date YYYY-MM-DD]`
  - exit 2 = no match, exit 3 = ambiguous → add more product words or use a sha prefix.
    Short words like "switch" match dozens of products — never pick one of the
    ambiguous matches by guess.
  - A revised clip has several clip-log rows; `add` binds to the NEWEST row (the shipped file).
- Report: `perf.py report --by hook_id|style|category [--min-views N]` → clips, views, CTR, CVR.
- Pick a hook: `perf.py pick-hook --category <cat> [--prefix gph-] [--candidates a,b]`
  - Excludes hooks used in the last 3 rows of the category, ranks the rest by
    Bayesian-smoothed CTR (prior 2% over 500 views, so unseen hooks still get
    explored but a proven winner outranks them); with no perf data it falls back to LRU.
  - Candidates default to the `` `<category>-N` `` ids found in `templates/hooks.md`.

## Collecting the numbers
- Fix supplies stats as screenshots of the Shopee Affiliate / Video dashboard (or
  Reels insights). Read them with `vision_analyze`, then one `perf.py add` per clip.
  Ask for a weekly screenshot when reporting a delivery; don't block a clip on it.
- Test the script against a COPY of the logs (temp dir with scripts/ logs/ templates/)
  when changing it — a test `add` against the real dir pollutes perf-log permanently.

## From house-rules.md (moved 2026-11-12)
- **When Fix asks what can be improved, ground the answer in the logs before proposing anything.** Count styles in `/opt/data/clips/logs/clip-log.jsonl`, read the latest rows' `notes`, and check that `perf-log.jsonl` holds data. If it is empty, say so, because every suggestion is then a guess until he sends stats. Rank each suggestion by credit cost (post-production = 0) and offer an A/B instead of switching the default.
- **`scripts/perf.py` + `/opt/data/clips/logs/perf-log.jsonl` — performance tracking (2026-11-05).** When Fix sends Affiliate/Shopee Video stats (screenshot or numbers), record each clip with `perf.py add --match … --views N --clicks N --orders N`; pick hooks with `perf.py pick-hook --category <cat>` (CTR-ranked when data exists, LRU otherwise). Detail: `references/performance-tracking.md`. Covers: `scripts/make_cover.py` (1080x1920 EN cover inside the safe zone) — feed it the PRE-subtitle/pill render, otherwise the clip's own pills and subs show through and the title can land on faces; vision-check the cover before sending.
