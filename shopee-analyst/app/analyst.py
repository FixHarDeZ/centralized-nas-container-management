"""Shopee Affiliate product picks, ranked by sales momentum x commission.

Stdlib only. Shopee credentials and the Telegram bot come from env (rendered
from the vault); nothing secret lives in config.json or /data.

Sales from productOfferV2 are lifetime totals, so momentum needs our own
snapshots: each run stores {item_id: sales} under DATA_DIR/snapshots and the
next run diffs against the one closest to 24 h old.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app import notify

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
BANGKOK = ZoneInfo("Asia/Bangkok")
DEFAULT_SHOPEE_URL = "https://open-api.affiliate.shopee.co.th/graphql"
TELEGRAM_LIMIT = 4000

# Field names and sortType=2 (ITEM_SOLD_DESC) match the third-party SDKs
# (saapi, shopee-afflib); not yet confirmed against a TH account — see --probe.
PRODUCT_QUERY = """
query Products($keyword: String, $sortType: Int, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, sortType: $sortType, page: $page, limit: $limit) {
    nodes {
      itemId productName shopName sales priceMin priceMax
      commissionRate commission ratingStar offerLink productLink
    }
    pageInfo { page limit hasNextPage }
  }
}
""".strip()


class ConfigError(RuntimeError):
    pass


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"ยังไม่ได้ตั้งค่า {name}")
    return value


def shopee_configured() -> bool:
    return all(
        os.environ.get(n, "").strip() for n in ("SHOPEE_APP_ID", "SHOPEE_APP_SECRET")
    )


def post_json(
    url: str, body: bytes, headers: dict[str, str], attempts: int = 3
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code}")
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = RuntimeError(type(exc).__name__)
        if attempt < attempts - 1:
            time.sleep(2**attempt)
    raise RuntimeError(f"เรียก API ไม่สำเร็จ: {last_error}")


def shopee_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    app_id = env("SHOPEE_APP_ID")
    secret = env("SHOPEE_APP_SECRET")
    url = os.environ.get("SHOPEE_API_URL") or DEFAULT_SHOPEE_URL
    payload = json.dumps(
        {"query": query, "variables": variables}, separators=(",", ":")
    )
    timestamp = str(int(time.time()))
    signature = hashlib.sha256(
        f"{app_id}{timestamp}{payload}{secret}".encode()
    ).hexdigest()
    authorization = (
        f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"
    )
    result = post_json(url, payload.encode(), {"Authorization": authorization})
    if result.get("errors"):
        # 10035 = account has no Open API access (also what bad credentials get).
        messages = "; ".join(str(e.get("message", e)) for e in result["errors"])
        raise RuntimeError(f"Shopee API ตอบ error: {messages}")
    return result["data"]


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize(node: dict[str, Any]) -> dict[str, Any]:
    price = to_float(node.get("priceMin")) or to_float(node.get("priceMax"))
    rate = to_float(node.get("commissionRate"))
    commission = to_float(node.get("commission")) or price * rate
    return {
        "item_id": str(node.get("itemId")),
        "name": str(node.get("productName") or "ไม่มีชื่อสินค้า"),
        "shop": str(node.get("shopName") or "-"),
        "sales": int(to_float(node.get("sales"))),
        "price": price,
        "commission_rate": rate,
        "commission": commission,
        "rating": to_float(node.get("ratingStar")),
        "link": str(node.get("offerLink") or node.get("productLink") or ""),
    }


def fetch_products(config: dict[str, Any]) -> list[dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    for keyword in config.get("keywords") or [None]:
        for page in range(1, int(config["pages_per_search"]) + 1):
            variables: dict[str, Any] = {
                "sortType": int(config["sort_type"]),
                "page": page,
                "limit": int(config["page_size"]),
            }
            if keyword:
                variables["keyword"] = keyword
            offer = shopee_request(PRODUCT_QUERY, variables)["productOfferV2"]
            for node in offer.get("nodes") or []:
                product = normalize(node)
                products[product["item_id"]] = product
            if not (offer.get("pageInfo") or {}).get("hasNextPage"):
                break
    return list(products.values())


def probe() -> dict[str, Any]:
    """One limit=1 call: proves signing, URL and schema on a real account."""
    offer = shopee_request(PRODUCT_QUERY, {"sortType": 2, "page": 1, "limit": 1})[
        "productOfferV2"
    ]
    return {"pageInfo": offer.get("pageInfo"), "nodes": offer.get("nodes") or []}


def parse_snapshot_time(path: Path) -> datetime:
    return datetime.strptime(path.stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def choose_baseline(snapshot_dir: Path, now: datetime) -> Path | None:
    """Prefer a snapshot closest to 24 hours old, then the oldest one over an hour old."""
    candidates = []
    for path in snapshot_dir.glob("*.json"):
        try:
            age = now - parse_snapshot_time(path)
        except ValueError:
            continue
        if age >= timedelta(hours=1):
            candidates.append((age, path))
    if not candidates:
        return None
    around_day = [
        c for c in candidates if timedelta(hours=20) <= c[0] <= timedelta(hours=30)
    ]
    if around_day:
        return min(around_day, key=lambda c: abs(c[0] - timedelta(hours=24)))[1]
    return max(candidates, key=lambda c: c[0])[1]


def rank_products(
    products: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]] | None,
    baseline_age_days: float | None,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    ranked = []
    for product in products:
        if product["rating"] < float(config["min_rating"]):
            continue
        if product["commission_rate"] < float(config["min_commission_rate"]):
            continue
        if product["sales"] < int(config["min_total_sales"]):
            continue
        item = dict(product)
        if (
            baseline is not None
            and baseline_age_days
            and product["item_id"] in baseline
        ):
            previous_sales = int(baseline[product["item_id"]].get("sales", 0))
            delta = max(0, product["sales"] - previous_sales)
            per_day = delta / baseline_age_days
            growth = delta / max(previous_sales, 50)
            item.update(
                sales_per_day=per_day,
                growth=growth,
                score=per_day * product["commission"] * (1 + min(growth, 1.0)),
                has_trend=True,
            )
        else:
            item.update(
                sales_per_day=None,
                growth=None,
                score=product["sales"] * product["commission"],
                has_trend=False,
            )
        ranked.append(item)
    # Measured momentum always beats a lifetime-sales estimate.
    ranked.sort(
        key=lambda p: (p["has_trend"] and p["score"] > 0, p["score"]), reverse=True
    )
    return ranked


def select_fresh(
    ranked: list[dict[str, Any]],
    sent: dict[str, str],
    now: datetime,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    top_n = int(config["top_n"])
    cutoff = now - timedelta(hours=int(config["repeat_cooldown_hours"]))

    def recently_sent(product: dict[str, Any]) -> bool:
        stamp = sent.get(product["item_id"])
        return bool(stamp) and datetime.fromisoformat(stamp) > cutoff

    fresh = [p for p in ranked if not recently_sent(p)]
    repeats = [p for p in ranked if recently_sent(p)]
    return (fresh + repeats)[:top_n]


def build_messages(
    picks: list[dict[str, Any]], now: datetime, trend_ready: bool
) -> list[str]:
    local = now.astimezone(BANGKOK)
    header = f"🛒 <b>สินค้าน่าทำคลิป</b>\n{local:%d/%m/%Y %H:%M} น."
    if not trend_ready:
        header += "\n⚠️ ข้อมูลยังไม่พอคำนวณยอดเพิ่มรายวัน รอบนี้จัดอันดับจากยอดขายสะสมและค่าคอม"
    if not picks:
        return [header + "\n\nรอบนี้ไม่มีสินค้าผ่านเกณฑ์"]
    blocks = []
    for index, product in enumerate(picks, 1):
        if product["sales_per_day"] is None:
            momentum = f"ขายสะสม {product['sales']:,} ชิ้น"
        else:
            momentum = (
                f"ขายเพิ่มประมาณ {product['sales_per_day']:,.0f} ชิ้น/วัน "
                f"(สะสม {product['sales']:,})"
            )
        link = html.escape(product["link"], quote=True)
        blocks.append(
            f"<b>{index}. {html.escape(product['name'][:90])}</b>\n"
            f"ราคา ฿{product['price']:,.0f} | ค่าคอม {product['commission_rate'] * 100:.1f}% "
            f"(≈฿{product['commission']:,.0f}/ชิ้น)\n"
            f"⭐ {product['rating']:.1f} | {momentum}\n"
            f"ร้าน: {html.escape(product['shop'][:50])}\n"
            f'<a href="{link}">เปิดสินค้า</a>'
        )
    return pack(header, blocks)


def pack(header: str, blocks: list[str]) -> list[str]:
    """Header + blocks into messages under TELEGRAM_LIMIT, never splitting a block."""
    messages, current = [], header
    for block in blocks:
        if len(current) + len(block) + 2 > TELEGRAM_LIMIT:
            messages.append(current)
            current = block
        else:
            current += "\n\n" + block
    messages.append(current)
    return messages


def send_telegram(text: str) -> None:
    """Raise when Telegram did not take it: history is saved only after delivery."""
    creds = notify.TgCreds(
        token=env("TELEGRAM_BOT_TOKEN"),
        chat=env("TELEGRAM_CHAT_ID"),
        parse_mode="HTML",
        disable_preview=True,
    )
    if "telegram" not in notify.Notifier(telegram=creds).send(text):
        raise RuntimeError("Telegram ไม่รับข้อความ")


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8"
    )
    tmp.replace(path)


def prune(
    snapshot_dir: Path, sent: dict[str, str], now: datetime, retention_days: int
) -> dict[str, str]:
    cutoff = now - timedelta(days=retention_days)
    for path in snapshot_dir.glob("*.json"):
        try:
            if parse_snapshot_time(path) < cutoff:
                path.unlink()
        except ValueError:
            continue
    return {k: v for k, v in sent.items() if datetime.fromisoformat(v) >= cutoff}


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or "/data")


def run(now: datetime | None = None, config_path: Path = CONFIG_PATH) -> int:
    now = now or datetime.now(UTC)
    config = load_json(config_path, None)
    if config is None:
        raise ConfigError(f"ไม่พบ {config_path}")
    snapshot_dir = data_dir() / "snapshots"
    sent_path = data_dir() / "sent.json"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    products = fetch_products(config)
    if not products:
        raise RuntimeError("Shopee API ไม่ส่งสินค้ากลับมา")

    baseline_path = choose_baseline(snapshot_dir, now)
    baseline, age_days = None, None
    if baseline_path:
        baseline = load_json(baseline_path, {})
        age_days = (now - parse_snapshot_time(baseline_path)).total_seconds() / 86400

    ranked = rank_products(products, baseline, age_days, config)
    sent = load_json(sent_path, {})
    picks = select_fresh(ranked, sent, now, config)
    for message in build_messages(picks, now, baseline is not None):
        send_telegram(message)

    # Persist only after delivery so a failed send can be retried cleanly.
    write_json(
        snapshot_dir / f"{now:%Y%m%dT%H%M%SZ}.json",
        {p["item_id"]: {"sales": p["sales"]} for p in products},
    )
    for pick in picks:
        sent[pick["item_id"]] = now.isoformat()
    write_json(sent_path, prune(snapshot_dir, sent, now, int(config["retention_days"])))
    log.info("fetched=%d eligible=%d sent=%d", len(products), len(ranked), len(picks))
    return len(picks)
