"""Affiliate tracking for Shop jobs: Sub IDs, posts, product snapshot, imported
Shopee reports, revenue summary and alert scan.

Nothing here writes the job record. A job's `revision` fences render results
and approvals (`set_render_result`, `approve_render`), and `update_job`
invalidates the approved plan — tracking what happened after a clip was posted
must not do either. Affiliate data therefore lives in its own tables with its
own revision counter, inside the same SQLite file (one volume to back up).

Attribution is computed at read time from Sub ID tokens, so report rows
imported before a Sub ID existed still match once it does, and unmatched rows
stay visible as an unattributed total instead of disappearing.
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from datetime import date, timedelta

from app.shop_report import parse
from app.shop_store import Conflict, Invalid, NotFound, Store, _json

CHANNELS = {"shopee": "sv", "facebook": "fb", "youtube": "yt"}
NO_CLICK_DAYS = 7
CAMPAIGN_WARN_DAYS = 2
MIN_COMPARE = 5  # posted products per group before the Flow/real comparison says anything
URL_IDS = (re.compile(r"/product/(\d+)/(\d+)"), re.compile(r"i\.(\d+)\.(\d+)"))


def sub_id(job_id: str, channel: str) -> str:
    """Letters and digits only: the one Sub ID shape every Shopee form accepts."""
    return "sf" + re.sub(r"[^0-9a-z]", "", job_id.lower())[:8] + CHANNELS[channel]


def product_ids(url: str) -> tuple[str, str]:
    for pattern in URL_IDS:
        match = pattern.search(url or "")
        if match:
            return match.group(1), match.group(2)
    return "", ""


def _day(value, label):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise Invalid(f"{label} must be YYYY-MM-DD") from exc


def _number(value, label, *, integer=False, upper=None):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise Invalid(f"invalid {label}")
    try:
        number = float(str(value).replace(",", ""))
    except ValueError as exc:
        raise Invalid(f"invalid {label}") from exc
    if not math.isfinite(number) or number < 0 or (upper is not None and number > upper):
        raise Invalid(f"invalid {label}")
    if integer:
        if number != int(number):
            raise Invalid(f"{label} must be a whole number")
        return int(number)
    return round(number, 2)


def _text(value, label, limit=500):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise Invalid(f"invalid {label}")
    return value.strip()


def _url(value, label):
    value = _text(value, label, 2000)
    if value and not value.startswith(("https://", "http://")):
        raise Invalid(f"{label} must be an HTTP URL")
    return value


def _blank(counts=None):
    return {"clicks": 0, "orders": 0, "commission_pending": 0.0, "commission_completed": 0.0,
            "commission_cancelled": 0.0, **(counts or {})}


class Affiliate:
    def __init__(self, store: Store):
        self.store = store
        with store._tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS affiliate (job_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS subids (sub_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, channel TEXT NOT NULL,
                                                   UNIQUE(job_id, channel));
                CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversions (key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS clicks (key TEXT PRIMARY KEY, day TEXT, subs TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS post_job ON posts(job_id);
            """)

    # ---- Sub IDs -----------------------------------------------------------

    def _ensure_subids(self, db, job_id):
        rows = dict(db.execute("SELECT channel, sub_id FROM subids WHERE job_id=?", (job_id,)).fetchall())
        for channel in CHANNELS:
            if channel not in rows:
                # Derived from the immutable job ID once, stored, never regenerated.
                value = sub_id(job_id, channel)
                db.execute("INSERT INTO subids VALUES (?,?,?)", (value, job_id, channel))
                rows[channel] = value
        return rows

    def _token_map(self, db):
        return {s: (j, c) for s, j, c in db.execute("SELECT sub_id, job_id, channel FROM subids")}

    # ---- Product snapshot (commission rate, campaign) ----------------------

    def _record(self, db, job_id):
        row = db.execute("SELECT body FROM affiliate WHERE job_id=?", (job_id,)).fetchone()
        if row:
            return json.loads(row[0])
        return {"job_id": job_id, "revision": 0, "product_url": "", "shop_id": "", "item_id": "", "shop_name": "",
                "category": "", "commission_rate": None, "commission_history": [], "campaign_name": "",
                "campaign_ends": None, "updated_at": None}

    def update_product(self, job_id: str, expected_revision: int, data: dict) -> dict:
        allowed = {"product_url", "shop_name", "category", "commission_rate", "campaign_name", "campaign_ends"}
        if set(data) - allowed:
            raise Invalid("unknown field")
        with self.store._tx() as db:
            self.store._job(db, job_id)
            record = self._record(db, job_id)
            if expected_revision != record["revision"]:
                raise Conflict("affiliate details changed; reload before saving")
            if "product_url" in data:
                record["product_url"] = _url(data["product_url"], "product URL")
                record["shop_id"], record["item_id"] = product_ids(record["product_url"])
            for key in ("shop_name", "category", "campaign_name"):
                if key in data:
                    record[key] = _text(data[key], key, 200)
            if "campaign_ends" in data:
                record["campaign_ends"] = _day(data["campaign_ends"], "campaign end")
            if "commission_rate" in data:
                rate = _number(data["commission_rate"], "commission rate", upper=100)
                if rate is not None and rate != record["commission_rate"]:
                    # Shopee changes rates often: keep what it was when, not just now.
                    record["commission_history"].append({"rate": rate, "at": time.time()})
                record["commission_rate"] = rate
            record["revision"] += 1
            record["updated_at"] = time.time()
            db.execute("INSERT OR REPLACE INTO affiliate VALUES (?,?)", (job_id, _json(record)))
            return record

    # ---- Posts -------------------------------------------------------------

    def _post_fields(self, db, job_id, data, *, partial):
        fields = {}
        if not partial or "channel" in data:
            if data.get("channel") not in CHANNELS:
                raise Invalid("invalid channel")
            fields["channel"] = data["channel"]
        if not partial or "url" in data:
            fields["url"] = _url(data.get("url"), "post URL")
        if not partial or "posted_on" in data:
            fields["posted_on"] = _day(data.get("posted_on"), "posted date") or date.today().isoformat()
        if "render_id" in data:
            render_id = data["render_id"] or None
            if render_id:
                render = self.store._get(db, "renders", render_id)
                if render["job_id"] != job_id or render["status"] != "ready":
                    raise Invalid("post must reference a finished render of this job")
            fields["render_id"] = render_id
        if "manual" in data:
            manual = data["manual"]
            if manual is None:
                fields["manual"] = None
            elif not isinstance(manual, dict) or set(manual) - {"clicks", "orders", "commission"}:
                raise Invalid("invalid manual metrics")
            else:
                values = {"clicks": _number(manual.get("clicks"), "clicks", integer=True),
                          "orders": _number(manual.get("orders"), "orders", integer=True),
                          "commission": _number(manual.get("commission"), "commission")}
                fields["manual"] = values if any(v is not None for v in values.values()) else None
        return fields

    def add_post(self, job_id: str, data: dict) -> dict:
        with self.store._tx() as db:
            job = self.store._job(db, job_id)
            fields = self._post_fields(db, job_id, data, partial=False)
            fields.setdefault("render_id", job.get("final_approved_render_id"))
            subs = self._ensure_subids(db, job_id)
            now = time.time()
            post = {"id": uuid.uuid4().hex, "job_id": job_id, "manual": None, "created_at": now, "updated_at": now,
                    "sub_id": subs[fields["channel"]], **fields}
            db.execute("INSERT INTO posts VALUES (?,?,?)", (post["id"], job_id, _json(post)))
            return post

    def _post(self, db, job_id, post_id):
        row = db.execute("SELECT body FROM posts WHERE id=? AND job_id=?", (post_id, job_id)).fetchone()
        if row is None:
            raise NotFound("post not found")
        return json.loads(row[0])

    def update_post(self, job_id: str, post_id: str, data: dict) -> dict:
        if set(data) - {"url", "posted_on", "render_id", "manual"}:
            raise Invalid("unknown field")
        with self.store._tx() as db:
            post = self._post(db, job_id, post_id)
            post.update(self._post_fields(db, job_id, data, partial=True), updated_at=time.time())
            db.execute("UPDATE posts SET body=? WHERE id=?", (_json(post), post_id))
            return post

    def delete_post(self, job_id: str, post_id: str) -> None:
        with self.store._tx() as db:
            self._post(db, job_id, post_id)
            db.execute("DELETE FROM posts WHERE id=?", (post_id,))

    def posted_counts(self) -> dict[str, int]:
        with self.store._tx() as db:
            return dict(db.execute("SELECT job_id, COUNT(*) FROM posts GROUP BY job_id").fetchall())

    # ---- Report import -----------------------------------------------------

    def import_report(self, filename: str, data: bytes) -> dict:
        report = parse(data)
        inserted = updated = 0
        with self.store._tx() as db:
            for row in report["rows"]:
                if report["kind"] == "conversions":
                    old = db.execute("SELECT body FROM conversions WHERE key=?", (row["key"],)).fetchone()
                    if old is None:
                        inserted += 1
                    elif json.loads(old[0]) != row:
                        updated += 1  # status moved, e.g. pending → completed
                    db.execute("INSERT OR REPLACE INTO conversions VALUES (?,?)", (row["key"], _json(row)))
                else:
                    subs = " ".join(row["sub_ids"])
                    cursor = db.execute("INSERT OR IGNORE INTO clicks VALUES (?,?,?)", (row["key"], row["day"], subs))
                    inserted += cursor.rowcount
            record = {"id": uuid.uuid4().hex, "kind": report["kind"], "filename": str(filename)[-200:],
                      "rows": len(report["rows"]), "inserted": inserted, "updated": updated,
                      "date_from": report["date_from"], "date_to": report["date_to"],
                      "commission_level": report["commission_level"], "headers": report["headers"][:60],
                      "matched": report["matched"],
                      "created_at": time.time()}
            db.execute("INSERT INTO imports VALUES (?,?)", (record["id"], _json(record)))
            return record

    def imports(self) -> list[dict]:
        with self.store._tx() as db:
            records = [json.loads(r[0]) for r in db.execute("SELECT body FROM imports")]
        return sorted(records, key=lambda r: r["created_at"], reverse=True)

    # ---- Attribution -------------------------------------------------------

    def _metrics(self, db):
        """{(job_id, channel): totals}, unattributed totals, unattributed conversions."""
        tokens = self._token_map(db)
        found, loose, loose_rows = {}, _blank(), []
        orders = {}

        def owner(subs):
            return next((tokens[t] for t in subs if t in tokens), None)

        for (body,) in db.execute("SELECT body FROM conversions"):
            row = json.loads(body)
            target = owner(row["sub_ids"])
            bucket = found.setdefault(target, _blank()) if target else loose
            bucket["commission_" + row["state"]] += row["commission"]
            if row["state"] != "cancelled":
                orders.setdefault(target, set()).add(row["order_id"])
            if not target:
                loose_rows.append(row)
        for (subs,) in db.execute("SELECT subs FROM clicks"):
            target = owner(subs.split())
            (found.setdefault(target, _blank()) if target else loose)["clicks"] += 1
        for target, ids in orders.items():
            (found.setdefault(target, _blank()) if target else loose)["orders"] = len(ids)
        for bucket in [*found.values(), loose]:
            for key in ("commission_pending", "commission_completed", "commission_cancelled"):
                bucket[key] = round(bucket[key], 2)
        return found, loose, loose_rows

    @staticmethod
    def _click_days(db):
        """{sub token: [days]} built once per scan; the alert scan holds the write lock."""
        days = {}
        for day, subs in db.execute("SELECT day, subs FROM clicks"):
            if day:
                for token in subs.split():
                    days.setdefault(token, []).append(day)
        return days

    def _click_coverage(self, db):
        days = [json.loads(r[0]).get("date_to") for r in db.execute("SELECT body FROM imports")
                if json.loads(r[0])["kind"] == "clicks"]
        return max((d for d in days if d), default=None)

    @staticmethod
    def _combine(imported, posts):
        total = dict(imported)
        manual = [p["manual"] for p in posts if p.get("manual")]
        for values in manual:
            total["clicks"] += values.get("clicks") or 0
            total["orders"] += values.get("orders") or 0
            total["commission_completed"] = round(total["commission_completed"] + (values.get("commission") or 0), 2)
        total["manual"] = bool(manual)
        return total

    def job_view(self, job_id: str) -> dict:
        with self.store._tx() as db:
            job = self.store._job(db, job_id)
            subs = self._ensure_subids(db, job_id)
            record = self._record(db, job_id)
            posts = sorted((json.loads(r[0]) for r in db.execute("SELECT body FROM posts WHERE job_id=?", (job_id,))),
                           key=lambda p: (p["posted_on"], p["created_at"]))
            found, _, loose_rows = self._metrics(db)
            renders = [json.loads(r[0]) for r in db.execute("SELECT body FROM renders WHERE job_id=?", (job_id,))]
        channels = {}
        for channel in CHANNELS:
            value = subs[channel]
            channel_posts = [p for p in posts if p["channel"] == channel]
            channels[channel] = {"sub_id": value, "posts": len(channel_posts),
                                 **self._combine(found.get((job_id, channel), _blank()), channel_posts)}
        same_item = [r for r in loose_rows if record["item_id"] and r.get("item_id") == record["item_id"]]
        return {"job_id": job_id, "product": record, "channels": channels, "posts": posts,
                "same_item_unattributed": {"rows": len(same_item),
                                           "commission": round(sum(r["commission"] for r in same_item
                                                                   if r["state"] != "cancelled"), 2)},
                "renders": [{"id": r["id"], "created_at": r["created_at"], "approved": bool(r.get("approved_at"))}
                            for r in renders if r["status"] == "ready"],
                "final_approved_render_id": job.get("final_approved_render_id")}

    # ---- Revenue summary ---------------------------------------------------

    @staticmethod
    def scene_kind(render) -> str:
        scenes = ((render or {}).get("snapshot") or {}).get("plan", {}).get("scenes", [])
        if not scenes:
            return "unknown"
        return "flow" if any(s.get("source") == "flow" for s in scenes) else "real"

    def summary(self) -> dict:
        with self.store._tx() as db:
            jobs = {j["id"]: j for j in (json.loads(r[0]) for r in db.execute("SELECT body FROM jobs"))}
            records = {r[0]: json.loads(r[1]) for r in db.execute("SELECT job_id, body FROM affiliate")}
            posts = [json.loads(r[0]) for r in db.execute("SELECT body FROM posts")]
            renders = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id, body FROM renders")}
            found, loose, _ = self._metrics(db)
            coverage = self._click_coverage(db)
        rows = []
        groups = {"channel": {}, "category": {}, "scene_kind": {}}
        for job_id, job in jobs.items():
            job_posts = [p for p in posts if p["job_id"] == job_id]
            imported = [found[k] for k in found if k[0] == job_id]
            if not job_posts and not imported:
                continue
            # The clip that went out, not the plan as edited since.
            kinds = {self.scene_kind(renders.get(p.get("render_id"))) for p in job_posts}
            kinds.discard("unknown")
            kind = "flow" if "flow" in kinds else "real" if kinds else "unknown"
            category = (records.get(job_id) or {}).get("category") or "ไม่ระบุ"
            channels = {}
            for channel in CHANNELS:
                channel_posts = [p for p in job_posts if p["channel"] == channel]
                totals = self._combine(found.get((job_id, channel), _blank()), channel_posts)
                if channel_posts or any(totals[k] for k in ("clicks", "orders", "commission_pending", "commission_completed")):
                    channels[channel] = {**totals, "posts": len(channel_posts)}
            total = _blank({"posts": 0})
            for values in channels.values():
                for key in total:
                    total[key] = round(total[key] + values.get(key, 0), 2)
            rows.append({"job_id": job_id, "name": job["name"], "category": category, "scene_kind": kind,
                         "commission_rate": (records.get(job_id) or {}).get("commission_rate"),
                         "channels": channels, "total": total})
            for group, key in (("category", category), ("scene_kind", kind)):
                bucket = groups[group].setdefault(key, _blank({"posts": 0, "products": 0}))
                bucket["products"] += 1
                for field in total:
                    bucket[field] = round(bucket[field] + total[field], 2)
            for channel, values in channels.items():
                bucket = groups["channel"].setdefault(channel, _blank({"posts": 0, "products": 0}))
                bucket["products"] += 1
                for field in _blank({"posts": 0}):
                    bucket[field] = round(bucket[field] + values.get(field, 0), 2)
        rows.sort(key=lambda r: r["total"]["commission_completed"] + r["total"]["commission_pending"], reverse=True)
        return {"rows": rows, "groups": groups, "unattributed": loose, "click_coverage": coverage,
                "comparison": self._compare(rows), "imports": self.imports()[:20]}

    @staticmethod
    def _compare(rows):
        out = {}
        for kind in ("flow", "real"):
            posted = [r for r in rows if r["scene_kind"] == kind and r["total"]["posts"]]
            earned = [r["total"]["commission_completed"] + r["total"]["commission_pending"] for r in posted]
            out[kind] = {"products": len(posted),
                         "average_commission": round(sum(earned) / len(earned), 2) if earned else None}
        enough = all(out[k]["products"] >= MIN_COMPARE for k in ("flow", "real"))
        out["enough"] = enough
        out["minimum"] = MIN_COMPARE
        return out

    # ---- Alerts ------------------------------------------------------------

    def due_alerts(self, today: date | None = None) -> list[dict]:
        """Alerts that should exist now. Delivery dedupes on event_id, so a
        repeated scan never sends twice."""
        today = today or date.today()
        alerts = []
        with self.store._tx() as db:
            coverage = self._click_coverage(db)
            click_days = self._click_days(db) if coverage else {}
            for (body,) in db.execute("SELECT body FROM posts"):
                post = json.loads(body)
                if post["channel"] == "shopee":
                    continue  # Sub ID on attached Shopee Video products is unverified
                due = (date.fromisoformat(post["posted_on"]) + timedelta(days=NO_CLICK_DAYS)).isoformat()
                # Only judge a post when an imported click report actually covers the week.
                if due > today.isoformat() or not coverage or coverage < due:
                    continue
                if (post.get("manual") or {}).get("clicks"):
                    continue
                if not any(d >= post["posted_on"] for d in click_days.get(post["sub_id"], ())):
                    alerts.append({"job_id": post["job_id"], "milestone": "no_clicks", "event_id": f"noclicks-{post['id']}",
                                   "detail": f"{post['channel']} · โพสต์ {post['posted_on']} · Sub ID {post['sub_id']}"})
            for (body,) in db.execute("SELECT body FROM affiliate"):
                record = json.loads(body)
                ends = record.get("campaign_ends")
                if not ends or not db.execute("SELECT 1 FROM posts WHERE job_id=?", (record["job_id"],)).fetchone():
                    continue
                if today.isoformat() <= ends <= (today + timedelta(days=CAMPAIGN_WARN_DAYS)).isoformat():
                    alerts.append({"job_id": record["job_id"], "milestone": "campaign_ending", "event_id": f"campaign-{ends}",
                                   "detail": f"{record.get('campaign_name') or 'แคมเปญ'} หมด {ends}"})
        return alerts

    def enqueue_alerts(self, today: date | None = None) -> int:
        alerts = self.due_alerts(today)
        for alert in alerts:
            self.store.notify(alert["job_id"], alert["milestone"], alert["event_id"],
                              event_id=alert["event_id"], detail=alert["detail"])
        return len(alerts)
