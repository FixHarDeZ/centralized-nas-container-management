"""GLO (สำนักงานสลากกินแบ่งรัฐบาล) public result API — stdlib urllib, no key.

Verified 2026-10-16 from the NAS:
- ``POST /api/lottery/getLatestLottery {}`` → latest draw (``response.status``
  plus ``data`` with every prize).
- ``POST /api/lottery/getLotteryResult {date,month,year}`` → that day's draw,
  or ``response: null`` when no draw happened that day.

The community API (lotto.api.rayriffy.com) many scripts use no longer resolves.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.request

from . import lotto

logger = logging.getLogger(__name__)

BASE = "https://www.glo.or.th/api/lottery"
UA = "Mozilla/5.0 (compatible; lotto-picker/1.0)"


def _post(path: str, body: dict, timeout: float = 20.0) -> dict | None:
    req = urllib.request.Request(
        f"{BASE}/{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    if not payload.get("status"):
        raise RuntimeError(f"GLO {path}: {payload.get('statusMessage')}")
    return payload.get("response")


def _to_draw(resp: dict | None) -> dict | None:
    if not resp or not resp.get("date"):
        return None
    data = resp.get("data")
    return {
        "date": resp["date"],
        "prizes": lotto.parse_prizes(data),
        "amounts": lotto.parse_amounts(data),
    }


def latest() -> dict | None:
    return _to_draw(_post("getLatestLottery", {}))


def on(day: dt.date) -> dict | None:
    """The draw held on ``day``, or None if there wasn't one."""
    return _to_draw(
        _post(
            "getLotteryResult",
            {"date": f"{day.day:02d}", "month": f"{day.month:02d}", "year": str(day.year)},
        )
    )
