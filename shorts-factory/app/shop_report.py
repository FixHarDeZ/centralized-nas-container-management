"""Parse Shopee Affiliate report exports. Pure functions; no storage.

The account has no Open API (ADR 0015), so numbers arrive as CSV files the
user exports from the Affiliate portal. Real header spellings were not
verified against a Thai export when this was written, so headers are matched
through an alias table after normalisation, and a file whose required columns
cannot be found is rejected with the headers it did have — never imported as
zero rows.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime


class ReportError(ValueError):
    pass


MAX_ROWS = 200_000


def norm(header: str) -> str:
    """Lower-case and drop everything that is not a letter or digit (Thai kept)."""
    return re.sub(r"[^0-9a-z฀-๿]", "", str(header).strip().lower())


ALIASES = {
    "order_id": ("orderid", "ordersn", "orderno", "ordernumber", "conversionid",
                 "รหัสคำสั่งซื้อ", "หมายเลขคำสั่งซื้อ", "เลขที่คำสั่งซื้อ"),
    "checkout_id": ("checkoutid", "รหัสการชำระเงิน", "รหัสเช็คเอาท์"),
    "item_id": ("itemid", "productid", "รหัสสินค้า"),
    "model_id": ("modelid", "variationid", "รหัสตัวเลือกสินค้า", "รหัสรุ่นสินค้า"),
    "item_name": ("itemname", "productname", "ชื่อสินค้า"),
    "shop_name": ("shopname", "ชื่อร้านค้า", "ชื่อร้าน"),
    "status": ("orderstatus", "conversionstatus", "status", "สถานะคำสั่งซื้อ",
               "สถานะการสั่งซื้อ", "สถานะ"),
    "order_time": ("purchasetime", "ordertime", "checkouttime", "ordertimeutc",
                   "เวลาสั่งซื้อ", "วันที่สั่งซื้อ", "เวลาที่สั่งซื้อ"),
    "item_commission": ("itemtotalcommission", "itemcommission", "itemnetcommission",
                        "ค่าคอมมิชชั่นสินค้า", "ค่าคอมมิชชันสินค้า", "ค่าคอมมิชชั่นรวมของสินค้า"),
    "order_commission": ("totalcommission", "ordercommission", "netcommission",
                         "affiliatenetcommission", "netaffiliatecommission", "commission",
                         "ค่าคอมมิชชั่นรวม", "ค่าคอมมิชชันรวม", "ค่าคอมมิชชั่นสุทธิ", "ค่าคอมมิชชั่น"),
    "click_id": ("clickid", "รหัสคลิก"),
    "click_time": ("clicktime", "เวลาคลิก", "วันที่คลิก"),
}
SUB_ID_HEADER = re.compile(r"^(subid\d?|utmcontent)$")
SUB_ID_TOKEN = re.compile(r"[0-9a-z]+")


def _columns(headers):
    found = {}
    by_norm = {norm(h): i for i, h in enumerate(headers)}
    for field, names in ALIASES.items():
        for name in names:
            if name in by_norm:
                found[field] = by_norm[name]
                break
    subs = [i for i, h in enumerate(headers) if SUB_ID_HEADER.match(norm(h))]
    return found, subs


def money(text) -> float:
    """`฿1,234.56`, `THB 12`, `-3.5` → float. Blank = 0."""
    cleaned = re.sub(r"[^0-9.\-]", "", str(text or ""))
    if cleaned in ("", "-", ".", "-."):
        return 0.0
    try:
        return round(float(cleaned), 2)
    except ValueError as exc:
        raise ReportError(f"unreadable amount: {text!r}") from exc


def state(raw: str) -> str:
    """Raw order status → pending / completed / cancelled."""
    value = str(raw or "").strip().lower()
    if any(w in value for w in ("cancel", "invalid", "fraud", "ยกเลิก", "ไม่ถูกต้อง", "ไม่สำเร็จ")):
        return "cancelled"
    if any(w in value for w in ("complete", "สำเร็จ", "เสร็จสมบูรณ์", "ยืนยันแล้ว")):
        return "completed"
    return "pending"


DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y")


def day(text) -> str | None:
    """Best-effort ISO date; Buddhist-era years are converted. Unknown = None."""
    value = str(text or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
        year = parsed.year - 543 if parsed.year > 2400 else parsed.year
        return date(year, parsed.month, parsed.day).isoformat()
    return None


def sub_tokens(cells) -> list[str]:
    """Every alphanumeric token across the Sub ID cells, lower-cased.

    Shopee may join several Sub IDs into one value (`a-b-c`), so a Sub ID made
    of letters and digits only is found whichever slot or joiner was used.
    """
    tokens = []
    for cell in cells:
        for token in SUB_ID_TOKEN.findall(str(cell or "").lower()):
            if token not in tokens:
                tokens.append(token)
    return tokens


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp874"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ReportError("file is not UTF-8 or Thai Windows-874 text")


def parse(data: bytes) -> dict:
    """Return {kind, rows, headers, matched, commission_level, date_from, date_to}.

    kind = "conversions" (has an order/checkout ID and a commission column) or
    "clicks" (has a click ID or click time). Anything else is rejected with the
    headers that were found so the alias table can be extended.
    """
    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    headers = next(reader, None)
    if not headers or not any(h.strip() for h in headers):
        raise ReportError("file has no header row")
    headers = [h.strip() for h in headers]
    columns, subs = _columns(headers)
    order_key = columns.get("order_id", columns.get("checkout_id"))
    commission = columns.get("item_commission", columns.get("order_commission"))
    if order_key is not None and commission is not None:
        kind = "conversions"
    elif "click_id" in columns or "click_time" in columns:
        kind = "clicks"
    else:
        missing = "order ID + commission" if order_key is not None or commission is not None else "order ID + commission, or click ID/time"
        raise ReportError(f"unrecognised report: missing {missing}. Headers found: " + ", ".join(headers[:40]))
    if not subs:
        raise ReportError("report has no Sub ID column; export with Sub ID columns. Headers found: " + ", ".join(headers[:40]))
    if kind == "conversions":
        # Without these the import would still "work": every order pending
        # forever, or row-number keys that duplicate on an overlapping re-import.
        if "status" not in columns:
            raise ReportError("conversion report has no order status column. Headers found: " + ", ".join(headers[:40]))
        if "item_id" not in columns and "model_id" not in columns:
            raise ReportError("conversion report has no item ID column. Headers found: " + ", ".join(headers[:40]))
    matched = {field: headers[index] for field, index in columns.items()}
    matched["sub_ids"] = ", ".join(headers[i] for i in subs)

    def cell(row, field):
        index = columns.get(field)
        return row[index].strip() if index is not None and index < len(row) else ""

    rows, days = [], []
    item_level = "item_commission" in columns
    seen_orders = set()
    for row in reader:
        if not any(c.strip() for c in row):
            continue
        if len(rows) >= MAX_ROWS:
            raise ReportError(f"report exceeds {MAX_ROWS} rows; export a shorter date range")
        tokens = sub_tokens(row[i] for i in subs if i < len(row))
        if kind == "conversions":
            order = row[order_key].strip() if order_key < len(row) else ""
            if not order:
                continue
            item, model = cell(row, "item_id"), cell(row, "model_id")
            amount = money(row[commission] if commission < len(row) else "")
            if not item_level:
                # An order-level total repeats on every item row; count it once.
                amount = 0.0 if order in seen_orders else amount
                seen_orders.add(order)
            when = day(cell(row, "order_time"))
            key = "|".join((order, item, model))
            rows.append({"key": key, "order_id": order, "item_id": item, "item_name": cell(row, "item_name"),
                         "shop_name": cell(row, "shop_name"), "status": cell(row, "status"),
                         "state": state(cell(row, "status")), "commission": amount, "day": when, "sub_ids": tokens})
        else:
            click = cell(row, "click_id")
            when = day(cell(row, "click_time"))
            key = click or hashlib.sha256("\x1f".join(row).encode()).hexdigest()
            rows.append({"key": key, "day": when, "sub_ids": tokens})
        if when:
            days.append(when)
    return {"kind": kind, "rows": rows, "headers": headers, "matched": matched,
            "commission_level": ("item" if item_level else "order") if kind == "conversions" else None,
            "date_from": min(days) if days else None, "date_to": max(days) if days else None}
