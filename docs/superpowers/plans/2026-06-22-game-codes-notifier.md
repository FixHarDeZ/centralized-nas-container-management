# Game Code Notifier Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New `game-codes/` stack that polls redeem-code sources for 4 mobile games and pushes only *new* codes to the same Telegram chat news-feed uses.

**Architecture:** One Python container, no web layer. A config-driven poller (`requests` + `beautifulsoup4`) loops every `POLL_INTERVAL` seconds, fetches each enabled source (JSON API for Genshin, HTML scrape for the other 3), diffs against a JSON state file on a Docker volume, and sends new codes to Telegram. Per-source first-run is silent (seed, don't spam). Scraper breakage (exception/HTTP error) fires a one-shot heartbeat alert on the healthy→broken edge and a recovery note on broken→healthy.

**Tech Stack:** Python 3.12-slim, `requests`, `beautifulsoup4`, `pytest`, Docker Compose. No FastAPI, no nginx, no SQLite — this is a poller, not a service.

## Global Constraints

- **Telegram reuse:** Post as news-feed's bot to news-feed's chat. Manifest maps `GAME_CODES_TELEGRAM_BOT_TOKEN: stacks.news_feed.telegram.bot_token` and `TELEGRAM_CHAT_ID: stacks.news_feed.telegram.chat_id` (same vault paths news-feed uses). Decided, not asked — user said "ใช้อันเดียวกับของ news-feed".
- **No port:** This stack exposes nothing. No nginx, no proxy. The CLAUDE.md stack-table "Port" cell is `—`.
- **Scaffolding decision:** Hand-roll the stack (don't use the `add-stack` skill) — its template assumes a web service + published port, which this poller has neither of. Follow news-feed's file conventions minus the web layer.
- **Timezone:** `TZ=Asia/Bangkok` in compose, like every other stack.
- **Image user:** Run as non-root `app` (uid 1000), matching news-feed's Dockerfile.
- **Security:** Never commit `.env`, real tokens, or real chat IDs. Secrets come only from the vault via the manifest.
- **Release rules (CLAUDE.md):** The `game-codes/README.md`, root `CLAUDE.md` stack-table row, and `.notes/` updates ship in the **same atomic commit** as the code.

---

### Task 1: Stack scaffold + Telegram-reuse manifest

**Files:**
- Create: `game-codes/requirements.txt`
- Create: `game-codes/secrets.manifest.yaml`
- Create: `game-codes/.gitignore`
- Create: `game-codes/.notes/.gitkeep`

**Interfaces:**
- Produces: a stack directory `render_env.py` recognizes; env vars `GAME_CODES_TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `POLL_INTERVAL`, `STATE_FILE`, `TZ` available at container runtime.

- [ ] **Step 1: Create `game-codes/requirements.txt`**

```
requests==2.32.3
beautifulsoup4==4.12.3

pytest==8.3.4
```

- [ ] **Step 2: Create `game-codes/secrets.manifest.yaml`**

```yaml
env:
  GAME_CODES_TELEGRAM_BOT_TOKEN: stacks.news_feed.telegram.bot_token
  TELEGRAM_CHAT_ID:              stacks.news_feed.telegram.chat_id

literals:
  POLL_INTERVAL: "1800"
  STATE_FILE:    /data/seen_codes.json
```

- [ ] **Step 3: Create `game-codes/.gitignore`**

```
.env
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Create `game-codes/.notes/.gitkeep`** (empty file, so the notes dir exists for the CLAUDE.md memory rule).

- [ ] **Step 5: Verify the manifest renders**

Run: `make secrets`
Expected: command succeeds and creates `game-codes/.env` containing `GAME_CODES_TELEGRAM_BOT_TOKEN=...`, `TELEGRAM_CHAT_ID=...`, `POLL_INTERVAL=1800`, `STATE_FILE=/data/seen_codes.json`. (If `make secrets` needs the age key and it's unavailable in this session, instead run `python scripts/render_env.py --stack game-codes --dry-run` or inspect that the manifest parses; note the limitation and move on.)

- [ ] **Step 6: Commit**

```bash
git add game-codes/requirements.txt game-codes/secrets.manifest.yaml game-codes/.gitignore game-codes/.notes/.gitkeep
git commit -m "feat(game-codes): scaffold stack + telegram-reuse manifest"
```

---

### Task 2: Source parsers (the bug-prone core)

**Files:**
- Create: `game-codes/game_code_notifier.py`
- Create: `game-codes/tests/__init__.py` (empty)
- Create: `game-codes/tests/fixtures/wuwa.html`
- Create: `game-codes/tests/fixtures/roe.html`
- Create: `game-codes/tests/fixtures/tod.html`
- Create: `game-codes/tests/fixtures/genshin.json`
- Test: `game-codes/tests/test_parsers.py`

**Interfaces:**
- Produces:
  - `SOURCES: list[dict]` — each entry has `key, name, type, url, redeem_url` plus type-specific keys.
  - `fetch(src: dict) -> list[dict]` — dispatches on `src["type"]`, returns `[{"code": str, "reward": str}, ...]`, **may raise** on network/HTTP errors.
  - `fetch_api_seria(src)`, `fetch_table_status(src)`, `fetch_section_regex(src)` — the three parser backends. Each takes the source dict and the already-fetched HTML/JSON text via an injected `text` arg for testability: signature `fetch_table_status(src, text) -> list[dict]`.

**Source decisions (verified server-rendered June 2026, so plain `requests` works — no JS):**
- **Genshin** → `https://hoyo-codes.seria.moe/codes?game=genshin` (JSON API, `status == "OK"` filter). Unchanged from the user's draft.
- **Wuthering Waves** → `https://wuthering.gg/codes`. Has a `Code | Status` table; keep only rows whose status says **Active**. This replaces the brittle game8 regex+blacklist entirely.
- **Throne of Desire** → `https://www.mustplay.in.th/content/page/69671b935ee1bb833c7a0884`. Regex `tod...` **but require ≥1 digit** so English words like "todays" don't match. Scope to a CSS section determined in Step 7.
- **Rise of Eros** → `https://cofregamers.com/en/rise-of-eros-redeem-code-list/`. 11-char alphanumeric codes; **must** scope to the codes section (CSS selector determined in Step 7) — a bare `[A-Za-z0-9]{11}` over the whole page is unsafe.

- [ ] **Step 1: Write failing parser tests**

First save fixtures. `genshin.json`:

```json
{"codes": [
  {"code": "GENSHINGIFT", "rewards": "Primogem x60", "status": "OK"},
  {"code": "EXPIREDONE",  "rewards": "Mora x10000", "status": "NOT_FOUND"}
]}
```

`wuwa.html` (minimal table with one Active, one Expired):

```html
<html><body>
<table>
  <tr><th>Code</th><th>Status</th></tr>
  <tr><td>WUTHERINGGIFT</td><td>Active</td></tr>
  <tr><td>BLACKSHORES</td><td>Expired</td></tr>
</table>
</body></html>
```

`roe.html` (codes inside a scoping container, plus a decoy 11-char string outside it):

```html
<html><body>
<p>RANDOMWORD11 should NOT be picked up.</p>
<div class="entry-content">
  <p>1gzUiopoEHg</p>
  <p>6D79Kt9M8XD</p>
</div>
</body></html>
```

`tod.html` (real code + an English decoy starting with "tod"):

```html
<html><body>
<div class="post-body">
  <p>tod18347 todays-news todhot666</p>
</div>
</body></html>
```

`tests/test_parsers.py`:

```python
from pathlib import Path

from game_code_notifier import (
    fetch_api_seria,
    fetch_table_status,
    fetch_section_regex,
)

FIX = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_seria_keeps_only_ok_status():
    src = {"type": "api_seria"}
    codes = {e["code"] for e in fetch_api_seria(src, _read("genshin.json"))}
    assert codes == {"GENSHINGIFT"}


def test_wuwa_keeps_only_active_rows():
    src = {"code_regex": r"^[A-Z0-9]{4,20}$"}
    codes = {e["code"] for e in fetch_table_status(src, _read("wuwa.html"))}
    assert codes == {"WUTHERINGGIFT"}  # Expired row dropped


def test_roe_scopes_to_section_and_ignores_decoys():
    src = {"scope_selector": ".entry-content", "code_regex": r"\b[A-Za-z0-9]{11}\b"}
    codes = {e["code"] for e in fetch_section_regex(src, _read("roe.html"))}
    assert codes == {"1gzUiopoEHg", "6D79Kt9M8XD"}
    assert "RANDOMWORD11" not in codes  # outside scope, not matched


def test_tod_regex_requires_digit():
    src = {"scope_selector": ".post-body", "code_regex": r"\btod(?=[a-z0-9]*\d)[a-z0-9]{3,}\b"}
    codes = {e["code"] for e in fetch_section_regex(src, _read("tod.html"))}
    assert codes == {"tod18347", "todhot666"}
    assert "todays" not in codes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd game-codes && python -m pytest tests/test_parsers.py -v`
Expected: FAIL — `ImportError` / `cannot import name 'fetch_api_seria' from 'game_code_notifier'`.

- [ ] **Step 3: Write `game-codes/game_code_notifier.py` parser layer**

```python
#!/usr/bin/env python3
"""Poll redeem-code sources for several mobile games and push *new* codes to
Telegram. One-shot (cron) or loop (POLL_INTERVAL>0, for the NAS container).

ENV:
  GAME_CODES_TELEGRAM_BOT_TOKEN  bot token (shared with news-feed)
  TELEGRAM_CHAT_ID               chat id (shared with news-feed)
  STATE_FILE                     seen-codes JSON path (default seen_codes.json)
  POLL_INTERVAL                  loop interval seconds; 0/unset = run once
"""
import html
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("GAME_CODES_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "seen_codes.json"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "0"))

HTTP_TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("game-codes")

SOURCES = [
    {
        "key": "genshin",
        "name": "Genshin Impact",
        "type": "api_seria",
        "url": "https://hoyo-codes.seria.moe/codes?game=genshin",
        "redeem_url": "https://genshin.hoyoverse.com/en/gift?code={code}",
    },
    {
        "key": "wuwa",
        "name": "Wuthering Waves",
        "type": "table_status",
        "url": "https://wuthering.gg/codes",
        # code cell must look like a WuWa code; status cell decides keep/drop
        "code_regex": r"^[A-Z0-9]{4,20}$",
        "redeem_url": None,  # WuWa redeems in-game only
    },
    {
        "key": "throne_of_desire",
        "name": "Throne of Desire",
        "type": "section_regex",
        "url": "https://www.mustplay.in.th/content/page/69671b935ee1bb833c7a0884",
        # ponytail: scope_selector set empirically in Step 7; require a digit so
        # Thai/English prose words starting "tod" don't match.
        "scope_selector": None,
        "code_regex": r"\btod(?=[a-z0-9]*\d)[a-z0-9]{3,}\b",
        "redeem_url": None,
    },
    {
        "key": "rise_of_eros",
        "name": "Rise of Eros",
        "type": "section_regex",
        "url": "https://cofregamers.com/en/rise-of-eros-redeem-code-list/",
        # ponytail: scope_selector REQUIRED — set empirically in Step 7. Without
        # it, an 11-char alnum regex over the whole page is a false-positive farm.
        "scope_selector": None,
        "code_regex": r"\b[A-Za-z0-9]{11}\b",
        "redeem_url": None,
    },
]


def _dedupe(entries: list[dict]) -> list[dict]:
    out, seen = [], set()
    for e in entries:
        if e["code"] in seen:
            continue
        seen.add(e["code"])
        out.append(e)
    return out


def fetch_api_seria(src: dict, text: str) -> list[dict]:
    data = json.loads(text)
    return [
        {"code": it["code"], "reward": (it.get("rewards") or "").strip()}
        for it in data.get("codes", [])
        if it.get("status") == "OK"
    ]


def fetch_table_status(src: dict, text: str) -> list[dict]:
    soup = BeautifulSoup(text, "html.parser")
    code_re = re.compile(src["code_regex"])
    out = []
    for row in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        code, status = cells[0], cells[1].lower()
        if not code_re.match(code):
            continue
        if "active" in status and "expired" not in status:
            out.append({"code": code, "reward": ""})
    return _dedupe(out)


def fetch_section_regex(src: dict, text: str) -> list[dict]:
    soup = BeautifulSoup(text, "html.parser")
    if src.get("scope_selector"):
        scope = " ".join(el.get_text(" ", strip=True) for el in soup.select(src["scope_selector"]))
    else:
        scope = soup.get_text(" ", strip=True)
    code_re = re.compile(src["code_regex"])
    return _dedupe([{"code": m.group(0), "reward": ""} for m in code_re.finditer(scope)])


_PARSERS = {
    "api_seria": fetch_api_seria,
    "table_status": fetch_table_status,
    "section_regex": fetch_section_regex,
}


def fetch(src: dict) -> list[dict]:
    """Download src['url'] and parse. Raises on network/HTTP error."""
    r = requests.get(src["url"], headers=HEADERS, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return _PARSERS[src["type"]](src, r.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd game-codes && python -m pytest tests/test_parsers.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add game-codes/game_code_notifier.py game-codes/tests/
git commit -m "feat(game-codes): source parsers with active-only + scoped regex"
```

- [ ] **Step 6: Verify live sources parse (manual smoke test, network required)**

Run:
```bash
cd game-codes && python -c "
import game_code_notifier as g
for s in g.SOURCES:
    try:
        print(f\"{s['name']:18} -> {[e['code'] for e in g.fetch(s)]}\")
    except Exception as e:
        print(f\"{s['name']:18} !! {e}\")
"
```
Expected: Genshin and WuWa print code lists (WuWa likely just `WUTHERINGGIFT`). ToD and RoE will likely print `[]` or garbage because `scope_selector` is still `None` — that is the cue for Step 7.

- [ ] **Step 7: Pin the two `scope_selector` values from the live HTML**

For ToD and RoE, fetch the page and find the container that wraps the codes:
```bash
cd game-codes && python -c "
import requests, game_code_notifier as g
for key in ('throne_of_desire', 'rise_of_eros'):
    s = next(x for x in g.SOURCES if x['key'] == key)
    open(f'/tmp/{key}.html','w').write(requests.get(s['url'], headers=g.HEADERS, timeout=20).text)
    print('wrote', key)
"
```
Open `/tmp/rise_of_eros.html` and `/tmp/throne_of_desire.html`, find the smallest CSS selector that contains the code list (e.g. `.entry-content`, `article .post-body`, a specific table). Set `scope_selector` for each source in `game_code_notifier.py`. Re-run the Step 6 smoke test until both print the expected real codes and nothing else. Commit:
```bash
git add game-codes/game_code_notifier.py
git commit -m "fix(game-codes): pin ToD/RoE scrape selectors from live HTML"
```

---

### Task 3: State, first-run-silent, Telegram, health alerts, main loop

**Files:**
- Modify: `game-codes/game_code_notifier.py` (append the runtime layer)
- Test: `game-codes/tests/test_runtime.py`

**Interfaces:**
- Consumes: `SOURCES`, `fetch(src)` from Task 2.
- Produces:
  - `load_state() -> dict` / `save_state(state)` — state shape `{"seen": {key: [codes]}, "health": {key: "ok"|"broken"}}`.
  - `diff_new(src, entries, state) -> list[dict]` — returns codes not in `state["seen"][key]`; **returns `[]` and seeds silently the first time a source key is seen** (key absent from `state["seen"]`). Always updates `state["seen"][key]`.
  - `send_telegram(text)` — POST to the news-feed bot/chat.
  - `run_once(state)` — full cycle; mutates+saves state.

- [ ] **Step 1: Write failing runtime tests**

`tests/test_runtime.py`:

```python
import game_code_notifier as g


def test_first_run_seeds_silently():
    state = {"seen": {}, "health": {}}
    entries = [{"code": "AAA", "reward": ""}, {"code": "BBB", "reward": ""}]
    new = g.diff_new({"key": "genshin"}, entries, state)
    assert new == []                                  # nothing reported first time
    assert set(state["seen"]["genshin"]) == {"AAA", "BBB"}  # but all recorded


def test_second_run_reports_only_new():
    state = {"seen": {"genshin": ["AAA"]}, "health": {}}
    entries = [{"code": "AAA", "reward": ""}, {"code": "CCC", "reward": ""}]
    new = g.diff_new({"key": "genshin"}, entries, state)
    assert [e["code"] for e in new] == ["CCC"]
    assert set(state["seen"]["genshin"]) == {"AAA", "CCC"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd game-codes && python -m pytest tests/test_runtime.py -v`
Expected: FAIL — `AttributeError: module 'game_code_notifier' has no attribute 'diff_new'`.

- [ ] **Step 3: Append the runtime layer to `game_code_notifier.py`**

```python
# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            s.setdefault("seen", {})
            s.setdefault("health", {})
            return s
        except Exception as e:
            log.warning("bad state file (%s), starting fresh", e)
    return {"seen": {}, "health": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def diff_new(src: dict, entries: list[dict], state: dict) -> list[dict]:
    """Codes not seen before. First time a source appears -> seed silently."""
    key = src["key"]
    first_time = key not in state["seen"]
    seen = set(state["seen"].get(key, []))
    fresh = [e for e in entries if e["code"] not in seen]
    state["seen"][key] = sorted(seen | {e["code"] for e in entries})
    return [] if first_time else fresh


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def send_telegram(text: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code != 200:
        log.error("telegram send failed: %s %s", resp.status_code, resp.text)


def format_message(src: dict, entry: dict) -> str:
    parts = [f"🎁 <b>{html.escape(src['name'])}</b>",
             f"โค้ด: <code>{html.escape(entry['code'])}</code>"]
    if entry.get("reward"):
        parts.append(f"ของรางวัล: {html.escape(entry['reward'])}")
    if src.get("redeem_url"):
        link = src["redeem_url"].format(code=entry["code"])
        parts.append(f'➡️ <a href="{html.escape(link)}">กดรับโค้ดที่นี่</a>')
    else:
        parts.append("ℹ️ เกมนี้กรอกโค้ดในเกมเท่านั้น")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Main cycle
#
# ponytail: health alert fires only on exception/HTTP error, on the
# healthy->broken edge (and recovery on broken->healthy). It does NOT treat a
# zero-code result as broken: WuWa legitimately has ~1 active code and is often
# empty between version livestreams, so alerting on zero would train the user to
# ignore the channel. Upgrade path: add a per-source "expect_nonzero" flag if a
# source should never be empty.
# --------------------------------------------------------------------------- #
def run_once(state: dict) -> None:
    for src in SOURCES:
        if src.get("enabled") is False:
            continue
        key = src["key"]
        try:
            entries = fetch(src)
        except Exception as e:
            log.error("fetch %s failed: %s", src["name"], e)
            if state["health"].get(key) != "broken":
                state["health"][key] = "broken"
                send_telegram(f"⚠️ <b>{html.escape(src['name'])}</b> scraper พัง: "
                              f"{html.escape(str(e))}\nอาจต้องอัปเดต selector/source")
                save_state(state)
            continue

        if state["health"].get(key) == "broken":
            state["health"][key] = "ok"
            send_telegram(f"✅ <b>{html.escape(src['name'])}</b> scraper กลับมาทำงานแล้ว")

        for entry in diff_new(src, entries, state):
            log.info("new code %-18s %s", src["name"], entry["code"])
            send_telegram(format_message(src, entry))
        save_state(state)


def main() -> None:
    state = load_state()
    if POLL_INTERVAL > 0:
        log.info("loop mode every %ds", POLL_INTERVAL)
        while True:
            run_once(state)
            time.sleep(POLL_INTERVAL)
    else:
        run_once(state)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
```

- [ ] **Step 4: Run all tests**

Run: `cd game-codes && python -m pytest -v`
Expected: 6 passed (4 parser + 2 runtime).

- [ ] **Step 5: Commit**

```bash
git add game-codes/game_code_notifier.py game-codes/tests/test_runtime.py
git commit -m "feat(game-codes): state, silent first-run seeding, health alerts"
```

---

### Task 4: Dockerfile + compose + deploy

**Files:**
- Create: `game-codes/Dockerfile`
- Create: `game-codes/docker-compose.yml`

**Interfaces:**
- Consumes: `requirements.txt`, `game_code_notifier.py`, `.env` (from `make secrets`).
- Produces: a container `game-codes` running the loop, state persisted on volume `game_codes_data:/data`.

- [ ] **Step 1: Create `game-codes/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN groupadd -g 1000 app && useradd -u 1000 -g app -s /bin/sh app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app game_code_notifier.py .

RUN mkdir -p /data && chown app:app /data

USER app
CMD ["python", "game_code_notifier.py"]
```

- [ ] **Step 2: Create `game-codes/docker-compose.yml`**

```yaml
services:
  game-codes:
    build: .
    container_name: game-codes
    restart: unless-stopped
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
    volumes:
      - game_codes_data:/data

volumes:
  game_codes_data:
```

- [ ] **Step 3: Build + run locally with the loop disabled (one-shot smoke)**

Run:
```bash
cd game-codes && docker compose build && \
docker compose run --rm -e POLL_INTERVAL=0 game-codes
```
Expected: container starts, logs each source line, and (since the volume is fresh) **seeds silently** — i.e. no Telegram spam, exit 0. On a second run it would only report genuinely new codes.

- [ ] **Step 4: Commit**

```bash
git add game-codes/Dockerfile game-codes/docker-compose.yml
git commit -m "feat(game-codes): dockerfile + compose (loop poller, data volume)"
```

---

### Task 5: Docs + notes (atomic with the feature, per release rules)

**Files:**
- Create: `game-codes/README.md`
- Create: `game-codes/.notes/00_INDEX.md`
- Create: `game-codes/.notes/daily_log.md`
- Modify: `CLAUDE.md` (add stack-table row)

- [ ] **Step 1: Create `game-codes/README.md`**

Cover: purpose (poll redeem codes → Telegram), the 4 sources and their type (API vs scrape) with the verified URLs, the **per-source first-run-silent** behaviour, the **health-alert** behaviour (exception-edge only, not zero-result), how to add a game (append to `SOURCES`), and the Telegram-reuse note (same bot+chat as news-feed via shared vault paths). State the honest caveat: **WuWa rarely has codes** (livestream-tied, usually 1 active or none), so most real traffic is Genshin/RoE.

- [ ] **Step 2: Create `.notes/00_INDEX.md`** — stack summary: services (single `game-codes` container), state file `/data/seen_codes.json` schema (`{seen, health}`), env vars, sources table, known gaps (RoE codes have no per-code expiry status; ToD/WuWa selectors may drift and need re-pinning).

- [ ] **Step 3: Create `.notes/daily_log.md`** — first entry dated `2026-06-22`: created the stack, verified sources, chose wuthering.gg over game8 for the Status column, fixed ToD regex to require a digit, reused news-feed Telegram.

- [ ] **Step 4: Add the CLAUDE.md stack-table row** (after the `secretary/` row, keeping table order):

```markdown
| `game-codes/` | Redeem-code notifier (Genshin/WuWa/ToD/RoE → Telegram) | — / — | Single Python poller, no web layer. Loops `POLL_INTERVAL` (1800s), diffs codes vs `/data/seen_codes.json`, sends new codes to **news-feed's** Telegram bot+chat (shared vault paths). Genshin via seria JSON API; WuWa scrapes `wuthering.gg` (Status=Active filter); ToD/RoE scrape with section-scoped regex. First-run per source seeds silently; scraper breakage fires a one-shot health alert on the healthy→broken edge. |
```

- [ ] **Step 5: Run the full test suite once more before the docs commit**

Run: `cd game-codes && python -m pytest -v`
Expected: 6 passed.

- [ ] **Step 6: Atomic docs commit**

```bash
git add game-codes/README.md game-codes/.notes/00_INDEX.md game-codes/.notes/daily_log.md CLAUDE.md
git commit -m "docs(game-codes): README, notes, CLAUDE.md stack row"
```

- [ ] **Step 7: Deploy** (when ready): `./scripts/deploy.sh`, then restart the stack:
`docker compose --project-directory game-codes/ -f game-codes/docker-compose.yml up -d --build`. Confirm `docker logs game-codes` shows the seed run with no Telegram spam.

---

## Self-Review

**Spec coverage:**
- "Source for WuWa scrape" → Task 2, `wuthering.gg/codes` with Status filter. ✅
- "Source for Rise of Eros scrape" → Task 2, `cofregamers.com` section-scoped. ✅
- "New stack" → Tasks 1, 4 (manifest, Dockerfile, compose). ✅
- "Notify via Telegram, same chat as news-feed" → Task 1 manifest reuses news-feed vault paths; Task 3 `send_telegram`. ✅
- "Don't spam on first run" → Task 3 `diff_new` first-run-silent + test. ✅
- Original script's first-run-spam bug → fixed (was: empty `seen` reported everything). ✅
- Original ToD whole-page regex false positives → fixed (digit-required + scope). ✅
- Scraper-breakage blindness (advisor) → Task 3 health-edge alert. ✅

**Placeholder scan:** ToD/RoE `scope_selector` are intentionally `None` in code with an explicit empirical step (Task 2 Step 7) to pin them from live HTML — this is a real, executable step, not a "TODO fill in later". All other code is complete.

**Type consistency:** `fetch_*` parsers all take `(src, text)` and return `[{"code", "reward"}]`. `fetch(src)` downloads then delegates. State shape `{"seen": {key: [str]}, "health": {key: str}}` consistent across `load_state`/`diff_new`/`run_once`. `diff_new(src, entries, state)` signature matches tests and caller.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-22-game-codes-notifier.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
