# Shorts Scripts are written from web search, and numbers must be cited

The model that writes a Script has no web access. Left alone it writes the
general-knowledge skeleton of a Topic and, where the Topic calls for numbers,
makes them up: six volleyball clips on 2026-08-29..31 came back as the same
essay, and two reached YouTube with invented figures. The answer until now was
to refuse such Topics (`RESULT_TOPIC` in `app/main.py`) — which also refused
harmless ones on a stray word (`ไม่แพ้ตัว MV`, 2026-09-28).

## Decision

Before a fresh Topic is written, `app/research.py` sends it to Tavily as typed
and hands up to five results (≤3,000 characters) to the model as a Fact sheet,
with a rule: numbers, years and results only from this material.
`script.validate()` enforces the rule — any number of two digits or more in a
card's narration that does not appear in the sheet sends the Script back.
The review message in Telegram lists the first three source URLs.

- **Every Topic is searched**, not only result-shaped ones. ~2s against a
  60-350s Script; general Topics get real facts too.
- **Best effort.** No key, a timeout (20s) or any error = no Fact sheet, and
  the Script is written as before. A revision reuses the sheet it was written
  from; searching again could change the numbers mid-edit.
- **Result-shaped Topics are now allowed** when the search finds something,
  and refused when it finds nothing. Unattended rounds (auto-pick) still
  refuse them outright: nobody reviews the Script before it renders.
- `!` still skips the guard and is not required to have sources.
- `/trends` still drops news/politics (25) and sport (17), and the rule against
  rumours about real people stays. Search makes a Script accurate; it does not
  make a rumour safe to publish.
- **No query planning by mimo.** Asking the model for search queries first
  costs another 30-90s on a model that thinks at ~30 tokens/s; Tavily takes
  natural language.

## Why Tavily

Built for LLM consumption (returns cleaned page text, not just snippets), free
tier 1,000 searches/month against roughly one per Clip. Brave would need a
second fetch for page text; Google CSE is 100/day and more setup.

## Consequences

- One more secret: `stacks.shorts_factory.tavily_api_key`. The dashboard does
  not get it (still no `env_file`, ADR 0007).
- Single-digit numbers pass unchecked — they are card counts and enumerations
  ("3 ข้อ") far more often than claims. A score like `3-2` is therefore not
  verified digit by digit; the reviewer sees the sources.
- The Fact sheet is stored on the Manifest (`research`), so where a number came
  from can be answered after the fact.
