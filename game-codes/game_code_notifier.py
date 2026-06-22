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
        # ponytail: scope_selector deferred to None (whole-page scope) — the build
        # sandbox can't reach mustplay.in.th to pin a selector. The digit-guard regex
        # below is the safety net; tighten scope_selector from an unfiltered network
        # (e.g. on the NAS) if false positives appear. require a digit so Thai/English
        # prose words starting "tod" don't match.
        "scope_selector": None,
        "code_regex": r"\btod(?=[a-z0-9]*\d)[a-z0-9]{3,}\b",
        "redeem_url": None,
        # ponytail: disabled — empirically today2024/today2025/etc. date
        # strings on the page match the digit-guard regex above and would be
        # pushed as fake "Throne of Desire" codes (spam). Re-enable once
        # scope_selector is pinned to the real code container from an
        # unfiltered network (e.g. the NAS); whole-page scope is what lets
        # date strings through.
        "enabled": False,
    },
    {
        "key": "rise_of_eros",
        "name": "Rise of Eros",
        "type": "section_regex",
        "url": "https://cofregamers.com/en/rise-of-eros-redeem-code-list/",
        # ponytail: pinned from live HTML (2026-06-22) — cofregamers.com wraps
        # the redeem-code table(s) in this container; excludes later prose
        # ("accelerates", "progression", "redemptions") that also happen to
        # be 11 chars and would otherwise false-positive.
        "scope_selector": ".codigo-tabla-container",
        "code_regex": r"\b[A-Za-z0-9]{11}\b",
        "redeem_url": None,
        # ponytail: RoE normally lists many active codes; unlike Genshin's
        # JSON API (legitimately 0 active codes sometimes) or WuWa (often
        # empty between livestreams), a 0-result here almost certainly means
        # .codigo-tabla-container drifted, not that the game ran out of codes.
        # Opt this source into the zero-result health guard below.
        "expect_nonzero": True,
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
        # Status may be plain text ("Active"/"Expired") or, on some sites,
        # only a button label ("COPY" for active, "Expired" for disabled) —
        # so treat anything NOT explicitly saying expired as still active.
        # A hypothetical third status (e.g. "Upcoming") would be kept, acceptable
        # for a notifier (low harm).
        if "expired" not in status:
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


def fetch(src: dict, retries: int = 3) -> list[dict]:
    """Download src['url'] and parse. Retries on 429 with exponential backoff."""
    last_exc = None
    for attempt in range(retries):
        r = requests.get(src["url"], headers=HEADERS, timeout=HTTP_TIMEOUT)
        if r.status_code == 429 and attempt < retries - 1:
            wait = 20 * (2 ** attempt)
            log.warning("429 from %s, retry %d/%d in %ds", src["name"], attempt + 1, retries, wait)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return _PARSERS[src["type"]](src, r.text)
    raise last_exc


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            s.setdefault("seen", {})
            s.setdefault("health", {})
            s.setdefault("rate_limited_until", {})
            return s
        except Exception as e:
            log.warning("bad state file (%s), starting fresh", e)
    return {"seen": {}, "health": {}, "rate_limited_until": {}}


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
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            log.error("telegram send failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        # ponytail: a Telegram outage (timeout/connection error) must not
        # propagate out of run_once->main and crash the container into a
        # restart loop — log and move on, same as the non-200 branch above.
        log.error("telegram send raised: %s", e)


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
# ponytail: health alert fires on exception/HTTP error, or on a zero-code
# result for sources that opt into "expect_nonzero" (currently only RoE) —
# both cases share the same health flag and the same healthy->broken edge
# guard (rate-limited to one alert, with recovery on broken->healthy). A
# plain zero-code result is NOT treated as broken by default: WuWa
# legitimately has ~1 active code and is often empty between version
# livestreams, so alerting on zero there would train the user to ignore the
# channel.
# --------------------------------------------------------------------------- #
def run_once(state: dict) -> None:
    now = time.time()
    first = True
    for src in SOURCES:
        if src.get("enabled") is False:
            continue
        key = src["key"]

        cooldown_until = state.get("rate_limited_until", {}).get(key, 0)
        if now < cooldown_until:
            log.info("skip %s (cooldown until %.0fs)", src["name"], cooldown_until - now)
            continue

        if not first:
            time.sleep(5)
        first = False

        try:
            entries = fetch(src)
        except Exception as e:
            log.error("fetch %s failed: %s", src["name"], e)
            if "429" in str(e):
                prev = state.get("rate_limited_until", {}).get(key, 0)
                cooldown = 1800 if now - prev < 3600 else 3600
                state.setdefault("rate_limited_until", {})[key] = now + cooldown
                log.warning("%s rate-limited, cooldown %ds", src["name"], cooldown)
                save_state(state)
            elif state["health"].get(key) != "broken":
                state["health"][key] = "broken"
                send_telegram(f"⚠️ <b>{html.escape(src['name'])}</b> scraper พัง: "
                              f"{html.escape(str(e))}\nอาจต้องอัปเดต selector/source")
                save_state(state)
            continue

        # ponytail: a successful fetch that returns [] is normally fine (see
        # module-docstring note above re WuWa/Genshin) — but a source that
        # opts into "expect_nonzero" (RoE) should never legitimately be
        # empty, so treat 0 results the same as the exception path: same
        # health flag, same healthy->broken edge-guard (rate-limited to one
        # alert), same recovery branch when codes reappear.
        if src.get("expect_nonzero") and not entries:
            log.error("fetch %s returned 0 codes (expect_nonzero)", src["name"])
            if state["health"].get(key) != "broken":
                state["health"][key] = "broken"
                send_telegram(f"⚠️ <b>{html.escape(src['name'])}</b> คืนค่า 0 โค้ด — "
                              f"source/selector อาจเปลี่ยน")
                save_state(state)
            continue

        if state["health"].get(key) == "broken":
            state["health"][key] = "ok"
            send_telegram(f"✅ <b>{html.escape(src['name'])}</b> scraper กลับมาทำงานแล้ว")

        state.get("rate_limited_until", {}).pop(key, None)
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
