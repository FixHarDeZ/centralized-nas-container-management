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
