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
import logging
import sys
import time

from config import POLL_INTERVAL, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
from http_client import get as http_get
from notify import Notifier, TgCreds
from parsers import parse
from state import diff_new, load_state, save_state

HTTP_TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
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
        "code_regex": r"^[A-Z0-9]{4,20}$",
        "redeem_url": None,
    },
    {
        "key": "throne_of_desire",
        "name": "Throne of Desire",
        "type": "section_regex",
        "url": "https://www.mustplay.in.th/content/page/69671b935ee1bb833c7a0884",
        "scope_selector": None,
        "code_regex": r"\btod(?=[a-z0-9]*\d)[a-z0-9]{3,}\b",
        "redeem_url": None,
        "enabled": False,
    },
    {
        "key": "rise_of_eros",
        "name": "Rise of Eros",
        "type": "section_regex",
        "url": "https://cofregamers.com/en/rise-of-eros-redeem-code-list/",
        "scope_selector": ".codigo-tabla-container",
        "code_regex": r"\b[A-Za-z0-9]{11}\b",
        "redeem_url": None,
        "expect_nonzero": True,
    },
]


def fetch(src: dict) -> list[dict]:
    """Download src['url'] and parse."""
    r = http_get(
        src["url"],
        headers=HEADERS,
        timeout=HTTP_TIMEOUT,
        retries=3,
        backoff=20.0,
    )
    return parse(src, r.text)


def send_telegram(text: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        log.error("GAME_CODES_TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return
    Notifier(
        telegram=TgCreds(
            TELEGRAM_TOKEN,
            TELEGRAM_CHAT_ID,
            parse_mode="HTML",
            disable_preview=True,
        ),
        timeout=HTTP_TIMEOUT,
    ).send(text)


def format_message(src: dict, entry: dict) -> str:
    parts = [
        f"🎁 <b>{html.escape(src['name'])}</b>",
        f"โค้ด: <code>{html.escape(entry['code'])}</code>",
    ]
    if entry.get("reward"):
        parts.append(f"ของรางวัล: {html.escape(entry['reward'])}")
    if src.get("redeem_url"):
        link = src["redeem_url"].format(code=entry["code"])
        parts.append(f'➡️ <a href="{html.escape(link)}">กดรับโค้ดที่นี่</a>')
    else:
        parts.append("ℹ️ เกมนี้กรอกโค้ดในเกมเท่านั้น")
    return "\n".join(parts)


def run_once(state: dict) -> None:
    now = time.time()
    first = True
    for src in SOURCES:
        if src.get("enabled") is False:
            continue
        key = src["key"]

        cooldown_until = state.get("rate_limited_until", {}).get(key, 0)
        if now < cooldown_until:
            log.info(
                "skip %s (cooldown until %.0fs)",
                src["name"],
                cooldown_until - now,
            )
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
                send_telegram(
                    f"⚠️ <b>{html.escape(src['name'])}</b> scraper พัง: "
                    f"{html.escape(str(e))}\nอาจต้องอัปเดต selector/source",
                )
                save_state(state)
            continue

        if src.get("expect_nonzero") and not entries:
            log.error("fetch %s returned 0 codes (expect_nonzero)", src["name"])
            if state["health"].get(key) != "broken":
                state["health"][key] = "broken"
                send_telegram(
                    f"⚠️ <b>{html.escape(src['name'])}</b> คืนค่า 0 โค้ด — "
                    f"source/selector อาจเปลี่ยน",
                )
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
