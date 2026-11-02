"""Entry point: a sleep loop that runs the analyst at each SLOTS time (Bangkok).

    python -m app.main                  # scheduler (container CMD)
    python -m app.main --once           # one run now
    python -m app.main --probe          # one limit=1 Shopee call, prints field names
    python -m app.main --telegram-test  # one test message

No HTTP, no port. A missed slot (container down) is skipped, not caught up:
three late recommendations in a row are noise. The loop touches
DATA_DIR/heartbeat every minute for the compose healthcheck.

Two sources, each skipped with a log line when its credentials are missing
(no Telegram — otherwise the error notifier would fire three times a day):
YouTube TH product clips (`app/clips.py`, always on) and the Shopee Affiliate
Open API (`app/analyst.py`, dormant until the account gets access). Any other
failure is reported to Telegram so a silent morning cannot look like "no picks".
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

from app import analyst, clips

log = logging.getLogger("shopee-analyst")
HEARTBEAT_SECONDS = 60


def slots() -> list[tuple[int, int]]:
    raw = os.environ.get("SLOTS") or "06:00,12:00,16:00"
    out = []
    for part in raw.split(","):
        hour, minute = part.strip().split(":")
        out.append((int(hour), int(minute)))
    return sorted(out)


def next_slot(now: datetime, times: list[tuple[int, int]]) -> datetime:
    """First slot strictly after `now` (aware, Bangkok)."""
    for day in (0, 1):
        base = now + timedelta(days=day)
        for hour, minute in times:
            at = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if at > now:
                return at
    raise ValueError("SLOTS is empty")


def _attempt(label: str, job) -> int:
    try:
        job()
        return 0
    except Exception as exc:
        log.error("%s failed: %s", label, exc)
        try:
            analyst.send_telegram(f"❌ {label} ทำงานไม่สำเร็จ\n{html.escape(str(exc))}")
        except Exception as notify_error:
            log.error("notify failed: %s", notify_error)
        return 1


def run_once() -> int:
    """Each source on its own: one failing never silences the other."""
    status = 0
    if clips.configured():
        status |= _attempt("คลิปสินค้ากำลังมา (YouTube)", clips.run)
    else:
        log.warning("YOUTUBE_* not set — skipping YouTube clips")
    if analyst.shopee_configured():
        status |= _attempt("ระบบแนะนำสินค้า Shopee", analyst.run)
    else:
        log.warning("SHOPEE_APP_ID/SHOPEE_APP_SECRET not set — skipping Shopee run")
    return status


def heartbeat() -> None:
    path = analyst.data_dir() / "heartbeat"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def loop() -> None:
    times = slots()
    while True:
        now = datetime.now(analyst.BANGKOK)
        due = next_slot(now, times)
        log.info("next run %s", due.isoformat(timespec="minutes"))
        while (left := (due - datetime.now(analyst.BANGKOK)).total_seconds()) > 0:
            heartbeat()
            time.sleep(min(left, HEARTBEAT_SECONDS))
        run_once()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--probe", action="store_true")
    group.add_argument("--telegram-test", action="store_true")
    args = parser.parse_args()
    if args.telegram_test:
        analyst.send_telegram("✅ ระบบแนะนำสินค้า Shopee เชื่อม Telegram สำเร็จ")
        print("telegram test sent")
        return 0
    if args.probe:
        result = analyst.probe()
        nodes = result["nodes"]
        print("pageInfo:", json.dumps(result["pageInfo"], ensure_ascii=False))
        print("fields:", sorted(nodes[0]) if nodes else "(no nodes)")
        print(json.dumps(nodes[:1], ensure_ascii=False, indent=1))
        return 0
    if args.once:
        return run_once()
    loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
