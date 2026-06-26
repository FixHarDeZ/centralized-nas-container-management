# Friendly Reminder — LINE Slip Auto-Pay + Mobile Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a payment slip image is posted in the LINE group, the system attaches it to the right installment payment and flips it to paid automatically; and the web UI's payment table becomes readable on mobile with a tidier look.

**Architecture:** Add a public, signature-verified `POST /webhook/line` to the existing FastAPI app (mirrors `maid-tracker`). On an image event the app downloads the LINE content immediately (the content URL is short-lived), then a **pure decision function** decides: exactly one outstanding payment → attach slip + mark paid; multiple → save the image to an in-memory pending slot and ask the group (by push) to type the installment name; a following name-text matches the pending slip to that installment. nginx exposes only `/webhook/line` without basic auth. The frontend table collapses to stacked cards under a CSS breakpoint.

**Tech Stack:** FastAPI, SQLite (stdlib `sqlite3`), APScheduler (already present), stdlib `urllib`/`hmac`/`hashlib`/`base64` only (no new deps), nginx:alpine sidecar, vanilla JS + CSS frontend.

## Global Constraints

- **No new Python dependencies.** Use stdlib `urllib`, `hmac`, `hashlib`, `base64`, `json`, `uuid`. (Image content fetch = `urllib.request`, same idiom as `app/notify.py`.)
- **Do NOT edit `app/notify.py`** — it is a vendored copy of `shared/notify.py` guarded by `tests/test_shared_sync.py`. Reuse `Notifier.send()` for all outbound LINE messages (push to group). Replies use push, not the LINE reply API (no replyToken plumbing).
- **"Outstanding" (ค้าง) is defined as:** `paid_at IS NULL AND (due_year, due_month) <= (current year, current month)` in the app timezone. Future-dated unpaid installments do NOT count. The auto-vs-ask split hinges on the count of *this* set. (Without this, every multi-installment item always has future unpaid rows and "auto" would never fire.)
- **Signature verification is mandatory in production.** HMAC-SHA256 over the raw body with the LINE channel secret; reject mismatches with HTTP 400. Additionally gate on `event.source.groupId == FRIENDLY_LINE_GROUP_ID` — ignore events from anywhere else. This endpoint flips payments to paid, so the trust boundary is not optional.
- **Idempotency:** webhook handling must tolerate LINE re-delivery and slips on already-paid payments as no-ops (never 409/500 back to LINE).
- **Webhook URL (already provisioned by user via DSM reverse proxy):** `https://fixhardez.synology.me:15066/webhook/line` → NAS `friendly-reminder-nginx:5066` → `friendly-reminder:8000`.
- **Vault path for the new secret:** `stacks.friendly_reminder.line.channel_secret` → env `FRIENDLY_LINE_CHANNEL_SECRET`.
- **TZ:** `Asia/Bangkok` via `os.environ["TZ"]` (already wired as `_TZ`).
- Run tests with: `python -m pytest friendly-reminder/tests/ -v`

---

## File Structure

- **Create `friendly-reminder/app/slip_match.py`** — Pure logic + pending store. No FastAPI, no network, no DB cursor objects passed around at the HTTP edge: it receives plain data (list of outstanding payment dicts, optional text) and returns a typed decision. Holds the in-memory pending-slip slot. This is the unit under test.
- **Modify `friendly-reminder/app/main.py`** — Add `POST /webhook/line`: read raw body, verify signature, gate on group, parse events, for image events fetch+save content, call `slip_match` decision, execute the DB side-effects (attach slip + mark paid) and push confirmations. Add a stdlib `urllib` GET helper for LINE content. Add `_LINE_SECRET` env read.
- **Create `friendly-reminder/tests/test_slip_match.py`** — Tests for the pure decision function and pending store.
- **Modify `friendly-reminder/secrets.manifest.yaml`** — Add `FRIENDLY_LINE_CHANNEL_SECRET` under `env:`.
- **Modify `secrets/vault.sops.yaml`** (via `make edit-vault`, MANUAL — user pastes the secret) — Add `channel_secret` under `stacks.friendly_reminder.line`.
- **Modify `friendly-reminder/nginx/nginx.conf`** — Add a public `location = /webhook/line` block (no `auth_basic`) proxying to the app; everything else stays behind basic auth.
- **Modify `friendly-reminder/app/static/style.css`** — Responsive: collapse `.payments-table` to stacked cards below ~640px (slip thumbnail stays visible); general polish (spacing, card shadows, summary stats).
- **Modify `friendly-reminder/app/static/index.html`** — Minor: ensure viewport + any wrapper class the CSS needs.
- **Modify `friendly-reminder/README.md` + root `CLAUDE.md`** — Document the webhook feature, the new vault key, and the manual LINE OA / DSM steps.

---

## Task 1: Pure slip-matching decision logic

**Files:**
- Create: `friendly-reminder/app/slip_match.py`
- Test: `friendly-reminder/tests/test_slip_match.py`

**Interfaces:**
- Produces:
  - `decide(outstanding: list[dict], saved_slip_path: str | None, text: str | None, group_id: str, pending: PendingStore, now_ts: float) -> Decision`
  - `@dataclass Decision`: fields `action: str` (`"attach_pay"` | `"ask"` | `"ignore"`), `payment_id: int | None`, `reply_text: str | None`, `slip_path: str | None`.
  - `class PendingStore` with `put(group_id, path, candidate_ids, ts)`, `take(group_id, now_ts) -> dict | None` (returns + clears if not expired; deletes stale entry's file is the caller's job), `TTL = 600`.
  - Each `outstanding` dict has keys: `id` (payment_id), `name` (installment name), `installment_number`, `num_installments`, `amount`.

**Behavior to encode:**
- **Image event path** (`saved_slip_path` set, `text` is None):
  - `len(outstanding) == 0` → `Decision("ignore", None, "ℹ️ ไม่มีงวดค้างชำระในขณะนี้", None)`.
  - `len(outstanding) == 1` → `Decision("attach_pay", outstanding[0]["id"], <confirm text>, saved_slip_path)`.
  - `len(outstanding) > 1` → `pending.put(...)`, `Decision("ask", None, <list of names>, saved_slip_path)`.
- **Text event path** (`text` set, `saved_slip_path` None):
  - `entry = pending.take(group_id, now_ts)`. If `None` → `Decision("ignore", None, None, None)` (no slip waiting; stay silent).
  - Else match `text` against the candidate installment names (substring, like maid-tracker's `e["name"] in text`):
    - exactly one candidate name in text → `Decision("attach_pay", that_payment_id, <confirm>, entry["path"])`.
    - zero or many → re-arm pending (`pending.put` again with same entry) and `Decision("ask", None, "❓ ไม่พบชื่อรายการที่ตรง พิมพ์ชื่อให้ชัดเจนนะ", entry["path"])`.

- [ ] **Step 1: Write the failing test**

```python
# friendly-reminder/tests/test_slip_match.py
import time
from app.slip_match import decide, PendingStore

OUT1 = [{"id": 10, "name": "iPhone 15", "installment_number": 3, "num_installments": 10, "amount": 3000.0}]
OUT2 = OUT1 + [{"id": 20, "name": "ตู้เย็น", "installment_number": 1, "num_installments": 6, "amount": 1500.0}]


def test_single_outstanding_image_attaches_and_pays():
    p = PendingStore()
    d = decide(OUT1, saved_slip_path="/data/slips/x.jpg", text=None, group_id="G", pending=p, now_ts=time.time())
    assert d.action == "attach_pay"
    assert d.payment_id == 10
    assert d.slip_path == "/data/slips/x.jpg"


def test_zero_outstanding_image_ignored_with_notice():
    p = PendingStore()
    d = decide([], saved_slip_path="/data/slips/x.jpg", text=None, group_id="G", pending=p, now_ts=time.time())
    assert d.action == "ignore"
    assert "ไม่มีงวดค้าง" in d.reply_text


def test_multi_outstanding_image_asks_and_stores_pending():
    p = PendingStore()
    d = decide(OUT2, saved_slip_path="/data/slips/y.jpg", text=None, group_id="G", pending=p, now_ts=100.0)
    assert d.action == "ask"
    assert "iPhone 15" in d.reply_text and "ตู้เย็น" in d.reply_text
    # pending now armed
    d2 = decide(OUT2, saved_slip_path=None, text="จ่ายตู้เย็นแล้ว", group_id="G", pending=p, now_ts=101.0)
    assert d2.action == "attach_pay"
    assert d2.payment_id == 20
    assert d2.slip_path == "/data/slips/y.jpg"


def test_text_without_pending_is_silent():
    p = PendingStore()
    d = decide(OUT2, saved_slip_path=None, text="จ่ายแล้ว", group_id="G", pending=p, now_ts=100.0)
    assert d.action == "ignore"
    assert d.reply_text is None


def test_pending_expires_after_ttl():
    p = PendingStore()
    p.put("G", "/data/slips/z.jpg", [10], 100.0)
    assert p.take("G", 100.0 + PendingStore.TTL + 1) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest friendly-reminder/tests/test_slip_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.slip_match'`

- [ ] **Step 3: Write minimal implementation**

```python
# friendly-reminder/app/slip_match.py
"""Pure decision logic for matching a LINE-posted slip image to a payment.

No network, no DB, no FastAPI — takes plain data, returns a Decision. The HTTP
edge (main.py) does signature checks, content download, and DB writes.

ponytail: pending slot is in-memory and single-per-group — lost on restart
(user re-posts), and two people posting slips in the same group within the TTL
collide. Key by source.userId instead of groupId if that ever bites.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decision:
    action: str                 # "attach_pay" | "ask" | "ignore"
    payment_id: int | None = None
    reply_text: str | None = None
    slip_path: str | None = None


class PendingStore:
    TTL = 600  # seconds

    def __init__(self) -> None:
        self._slot: dict[str, dict] = {}

    def put(self, group_id: str, path: str, candidate_ids: list[int], ts: float) -> None:
        self._slot[group_id] = {"path": path, "candidate_ids": candidate_ids, "ts": ts}

    def take(self, group_id: str, now_ts: float) -> dict | None:
        entry = self._slot.get(group_id)
        if entry is None:
            return None
        if now_ts - entry["ts"] > self.TTL:
            self._slot.pop(group_id, None)
            return None
        self._slot.pop(group_id, None)
        return entry


def _confirm(name: str, number: int, total: int, amount: float) -> str:
    return f"✅ บันทึกสลิป + จ่ายแล้ว — {name} งวดที่ {number}/{total} ฿{amount:,.2f}"


def decide(outstanding, saved_slip_path, text, group_id, pending, now_ts) -> Decision:
    # ── Image event ──────────────────────────────────────────────
    if saved_slip_path is not None:
        if not outstanding:
            return Decision("ignore", reply_text="ℹ️ ไม่มีงวดค้างชำระในขณะนี้")
        if len(outstanding) == 1:
            p = outstanding[0]
            return Decision(
                "attach_pay", p["id"],
                _confirm(p["name"], p["installment_number"], p["num_installments"], p["amount"]),
                saved_slip_path,
            )
        pending.put(group_id, saved_slip_path, [p["id"] for p in outstanding], now_ts)
        names = "\n".join(f"  • {p['name']}" for p in outstanding)
        return Decision(
            "ask",
            reply_text=f"❓ มีหลายรายการค้างชำระ พิมพ์ชื่อรายการที่จ่ายนะ:\n{names}",
            slip_path=saved_slip_path,
        )

    # ── Text event ───────────────────────────────────────────────
    if text is not None:
        entry = pending.take(group_id, now_ts)
        if entry is None:
            return Decision("ignore")
        matched = [p for p in outstanding
                   if p["id"] in entry["candidate_ids"] and p["name"] in text]
        if len(matched) == 1:
            p = matched[0]
            return Decision(
                "attach_pay", p["id"],
                _confirm(p["name"], p["installment_number"], p["num_installments"], p["amount"]),
                entry["path"],
            )
        # re-arm so the user can try again within the TTL
        pending.put(group_id, entry["path"], entry["candidate_ids"], now_ts)
        return Decision("ask", reply_text="❓ ไม่พบชื่อรายการที่ตรง พิมพ์ชื่อให้ชัดเจนนะ", slip_path=entry["path"])

    return Decision("ignore")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest friendly-reminder/tests/test_slip_match.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add friendly-reminder/app/slip_match.py friendly-reminder/tests/test_slip_match.py
git commit -m "feat(friendly-reminder): pure slip-to-payment matching logic"
```

---

## Task 2: Webhook endpoint + content download wiring

**Files:**
- Modify: `friendly-reminder/app/main.py`
- Test: `friendly-reminder/tests/test_slip_match.py` (extend — see below; the heavy logic is already covered, this adds one signature-helper test)

**Interfaces:**
- Consumes: `decide`, `PendingStore`, `Decision` from Task 1; `SLIPS_DIR`, `_open_db`, `_now_str`, `_fmt`, `THAI_MONTHS`, `_notifier`, `_LINE_TOKEN`, `_LINE_GROUP` from existing `main.py`.
- Produces: `POST /webhook/line` route; module-level `_pending = PendingStore()`; `_LINE_SECRET` env; helpers `_verify_line_signature(body: bytes, sig: str) -> bool`, `_fetch_line_content(message_id: str) -> tuple[bytes, str]` (returns content bytes + a file extension guessed from `Content-Type`), `_outstanding_payments(conn) -> list[dict]`, `_apply_attach_pay(conn, payment_id, slip_path)`.

**Key implementation notes (bake in, do not paraphrase as TODO):**
- Read body raw with `await request.body()` BEFORE parsing — signature is over raw bytes.
- `_LINE_SECRET = os.environ.get("FRIENDLY_LINE_CHANNEL_SECRET", "")`. If empty, log a warning at startup but still **reject** all webhook calls with 503 (mis-config must not silently accept unsigned writes). (Tests/dev that need to bypass do so by setting the secret and signing.)
- `_outstanding_payments`: `SELECT p.id, p.installment_number, p.amount, i.name, i.num_installments FROM payments p JOIN installments i ON i.id=p.installment_id WHERE p.paid_at IS NULL AND (p.due_year < ? OR (p.due_year = ? AND p.due_month <= ?)) ORDER BY p.due_year, p.due_month` with `(year, year, month)`.
- Image content: `_fetch_line_content` GETs `https://api-data.line.me/v2/bot/message/{message_id}/content` with `Authorization: Bearer {_LINE_TOKEN}`, reads bytes, maps `Content-Type` (`image/jpeg`→`.jpg`, `image/png`→`.png`, else `.jpg`). Save to `SLIPS_DIR / f"line_{message_id}_{uuid4().hex[:8]}{ext}"`. **Fetch happens when the image event arrives**, before any branching — the content URL expires.
- `_apply_attach_pay`: idempotent — `UPDATE payments SET paid_at = COALESCE(paid_at, ?), slip_filename = ? WHERE id = ?`, then commit. (Already-paid stays at its original `paid_at`; slip still attaches.) Move/rename the saved temp file into its final slip filename if your download names differ from the stored `slip_filename`; store just the basename in DB (matches existing `slip_filename` convention served by `/api/slips/{filename}`).
- Event loop: for each `event` where `event["type"]=="message"` and `event["source"].get("groupId")==_LINE_GROUP`:
  - `message.type=="image"` → download+save → `decide(outstanding, saved_path_basename, None, group, _pending, now)`.
  - `message.type=="text"` → `decide(outstanding, None, text, group, _pending, now)`.
  - On `Decision.action=="attach_pay"`: `_apply_attach_pay`, then `_notifier.send(reply_text)`.
  - On `"ask"`: `_notifier.send(reply_text)`.
  - On `"ignore"`: send `reply_text` only if not None.
- Always return `{"ok": True}` with 200 to LINE unless signature/JSON invalid (400) or secret missing (503) — never 409/500 for business cases.
- Guard the whole per-event body in try/except logging; one bad event must not 500 the batch (LINE would retry forever).

- [ ] **Step 1: Write the failing test (signature helper)**

```python
# append to friendly-reminder/tests/test_slip_match.py
import base64, hashlib, hmac


def test_signature_roundtrip(monkeypatch):
    import os
    os.environ["FRIENDLY_LINE_CHANNEL_SECRET"] = "s3cr3t"
    from importlib import reload
    import app.main as m
    reload(m)
    body = b'{"events":[]}'
    good = base64.b64encode(hmac.new(b"s3cr3t", body, hashlib.sha256).digest()).decode()
    assert m._verify_line_signature(body, good) is True
    assert m._verify_line_signature(body, "bad") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest friendly-reminder/tests/test_slip_match.py::test_signature_roundtrip -v`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute '_verify_line_signature'`

- [ ] **Step 3: Implement the endpoint and helpers in `main.py`**

Add near the other env reads (after line 29):

```python
_LINE_SECRET = os.environ.get("FRIENDLY_LINE_CHANNEL_SECRET", "")
```

Add imports at top (`hmac`, `hashlib`, `base64`, `json`, `urllib.request`, `Request` from fastapi):

```python
import base64
import hashlib
import hmac
import json
import urllib.request
from fastapi import Request
from app.slip_match import PendingStore, decide
```

Add module-level store (after `_scheduler = ...`):

```python
_pending = PendingStore()
_LINE_CONTENT_URL = "https://api-data.line.me/v2/bot/message/{mid}/content"
_CT_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
```

Add helpers (near other helpers):

```python
def _verify_line_signature(body: bytes, signature: str) -> bool:
    if not _LINE_SECRET:
        return False
    computed = base64.b64encode(
        hmac.new(_LINE_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(computed, signature)


def _fetch_line_content(message_id: str) -> tuple[bytes, str]:
    req = urllib.request.Request(
        _LINE_CONTENT_URL.format(mid=message_id),
        headers={"Authorization": f"Bearer {_LINE_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        ext = _CT_EXT.get(resp.headers.get("Content-Type", "").split(";")[0].strip(), ".jpg")
        return resp.read(), ext


def _outstanding_payments(conn) -> list[dict]:
    today = date.today()
    rows = conn.execute(
        "SELECT p.id, p.installment_number, p.amount, i.name, i.num_installments "
        "FROM payments p JOIN installments i ON i.id = p.installment_id "
        "WHERE p.paid_at IS NULL AND (p.due_year < ? OR (p.due_year = ? AND p.due_month <= ?)) "
        "ORDER BY p.due_year, p.due_month",
        (today.year, today.year, today.month),
    ).fetchall()
    return [dict(r) for r in rows]


def _apply_attach_pay(conn, payment_id: int, slip_filename: str) -> None:
    conn.execute(
        "UPDATE payments SET paid_at = COALESCE(paid_at, ?), slip_filename = ? WHERE id = ?",
        (_now_str(), slip_filename, payment_id),
    )
    conn.commit()
```

Add the route (after the other routes, before the static mount):

```python
@app.post("/webhook/line")
async def line_webhook(request: Request):
    if not _LINE_SECRET:
        raise HTTPException(503, "Webhook not configured")
    body = await request.body()
    if not _verify_line_signature(body, request.headers.get("X-Line-Signature", "")):
        raise HTTPException(400, "Invalid LINE signature")
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    import time as _time
    for event in data.get("events", []):
        try:
            if event.get("type") != "message":
                continue
            if (event.get("source") or {}).get("groupId") != _LINE_GROUP:
                continue
            msg = event.get("message", {})
            conn = _open_db()
            try:
                outstanding = _outstanding_payments(conn)
                saved_basename = None
                text = None
                if msg.get("type") == "image":
                    content, ext = _fetch_line_content(msg["id"])
                    saved_basename = f"line_{msg['id']}_{uuid.uuid4().hex[:8]}{ext}"
                    (SLIPS_DIR / saved_basename).write_bytes(content)
                elif msg.get("type") == "text":
                    text = (msg.get("text") or "").strip()
                else:
                    continue

                d = decide(outstanding, saved_basename, text,
                           _LINE_GROUP, _pending, _time.time())
                if d.action == "attach_pay" and d.payment_id is not None:
                    _apply_attach_pay(conn, d.payment_id, d.slip_path)
                if d.reply_text:
                    _notifier.send(d.reply_text)
            finally:
                conn.close()
        except Exception:  # one bad event must not 500 the batch (LINE retries)
            import logging
            logging.getLogger(__name__).exception("webhook event failed")
    return {"ok": True}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest friendly-reminder/tests/ -v`
Expected: PASS (all, including `test_signature_roundtrip`)

- [ ] **Step 5: Commit**

```bash
git add friendly-reminder/app/main.py friendly-reminder/tests/test_slip_match.py
git commit -m "feat(friendly-reminder): LINE webhook attaches slip + marks paid"
```

---

## Task 3: nginx — expose `/webhook/line` publicly

**Files:**
- Modify: `friendly-reminder/nginx/nginx.conf`

**Interfaces:** none (config only). The DSM reverse proxy already forwards `https://fixhardez.synology.me:15066/` → this nginx on port 80.

- [ ] **Step 1: Add the public location ABOVE `location /`**

Edit `friendly-reminder/nginx/nginx.conf` — insert before the existing `location /` block:

```nginx
    # Public: LINE webhook (no basic auth; the app verifies X-Line-Signature).
    location = /webhook/line {
        proxy_pass          http://friendly-reminder:8000;
        proxy_http_version  1.1;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
    }
```

- [ ] **Step 2: Validate config syntax locally (optional, if docker available)**

Run: `docker run --rm -v "$PWD/friendly-reminder/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine nginx -t`
Expected: `syntax is ok` / `test is successful` (upstream name won't resolve standalone — that's fine; `-t` only parses).

- [ ] **Step 3: Commit**

```bash
git add friendly-reminder/nginx/nginx.conf
git commit -m "feat(friendly-reminder): expose public /webhook/line in nginx"
```

---

## Task 4: Add the LINE channel secret to the vault (MANUAL — needs user)

**Files:**
- Modify: `friendly-reminder/secrets.manifest.yaml`
- Modify: `secrets/vault.sops.yaml` (via `make edit-vault` — user pastes the real secret)

**This task requires the user.** The channel secret value cannot be read from the repo. Use the `adding-vault-secret` skill.

- [ ] **Step 1: Add the env mapping to the manifest**

Edit `friendly-reminder/secrets.manifest.yaml`, under `env:`:

```yaml
  FRIENDLY_LINE_CHANNEL_SECRET:       stacks.friendly_reminder.line.channel_secret
```

- [ ] **Step 2: Add the secret to the vault (user runs)**

```bash
make edit-vault
# add under stacks.friendly_reminder.line:
#   channel_secret: <paste channel secret from LINE Developers console>
```

Also add the same key to `secrets/test-vault.sops.yaml` (a dummy value) so `make check` stays green — the manifest schema/vault-sync test requires every `env:` path to exist in the test vault.

- [ ] **Step 3: Regenerate envs and verify**

```bash
make secrets
make check
grep FRIENDLY_LINE_CHANNEL_SECRET friendly-reminder/.env   # present, non-empty
```
Expected: `make check` passes; the key is present in the rendered `.env`.

- [ ] **Step 4: Commit**

```bash
git add friendly-reminder/secrets.manifest.yaml secrets/vault.sops.yaml secrets/test-vault.sops.yaml
git commit -m "feat(friendly-reminder): add LINE channel_secret for webhook signature"
```

---

## Task 5: Mobile-responsive payment table + visual polish

**Files:**
- Modify: `friendly-reminder/app/static/style.css`
- Modify: `friendly-reminder/app/static/index.html` (only if a wrapper hook is needed)

This is a CSS task — no TDD ceremony. The current `.payments-table` has 6 columns and overflows on phones, hiding the slip column. Collapse it to stacked cards below 640px.

- [ ] **Step 1: Add a responsive breakpoint that turns table rows into cards**

Append to `friendly-reminder/app/static/style.css`:

```css
/* ── Mobile: collapse the 6-col payments table into stacked cards ───────── */
@media (max-width: 640px) {
  .payments-table thead { display: none; }
  .payments-table, .payments-table tbody, .payments-table tr, .payments-table td {
    display: block;
    width: 100%;
  }
  .payments-table tr {
    margin-bottom: 0.75rem;
    border: 1px solid var(--border, #2a2a3a);
    border-radius: 10px;
    padding: 0.5rem 0.75rem;
    background: var(--card, #1b1b27);
  }
  .payments-table td {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    padding: 0.3rem 0;
    border: none;
    text-align: right;
  }
  /* label each cell using the header text */
  .payments-table td::before {
    content: attr(data-label);
    font-size: 0.8rem;
    color: var(--text-muted, #888);
    text-align: left;
  }
  .payments-table td.slip-cell { justify-content: flex-end; }
  .slip-thumb { max-width: 96px; height: auto; }
}
```

- [ ] **Step 2: Emit `data-label` on each `<td>` so the mobile labels show**

In `friendly-reminder/app/static/app.js`, in `loadPaymentsTable`, change the row template's cells to carry labels:

```javascript
      html += `
        <tr id="prow-${p.id}">
          <td data-label="งวดที่">${p.installment_number}</td>
          <td data-label="กำหนดชำระ" class="${dueClass}">${dueTxt}</td>
          <td data-label="ยอด (฿)">${fmt(p.amount)}</td>
          <td data-label="สถานะ">${statusHtml}</td>
          <td data-label="สลิป" class="slip-cell">${slipHtml}</td>
          <td data-label="">${actionHtml}</td>
        </tr>`;
```

- [ ] **Step 3: Polish pass (spacing, summary cards, buttons)**

Apply tasteful, low-risk refinements in `style.css` (do not restructure the palette): increase `.card` padding and add a subtle shadow; make `.summary-stat .value` larger/bolder; give `.btn-pay`/`.btn-primary` a hover state; ensure `min-width: 44px` tap targets on `.btn-pay`, `.btn-unpay`, `.btn-slip`. Keep the existing dark theme variables.

- [ ] **Step 4: Eyeball it**

Run the app locally or rely on NAS deploy; open at a 390px viewport (Chrome devtools) and confirm: each payment renders as a card, the slip thumbnail is visible, no horizontal scroll.

- [ ] **Step 5: Commit**

```bash
git add friendly-reminder/app/static/style.css friendly-reminder/app/static/app.js
git commit -m "feat(friendly-reminder): responsive payment cards on mobile + polish"
```

---

## Task 6: Docs + deploy + manual LINE Official Account setup

**Files:**
- Modify: `friendly-reminder/README.md`
- Modify: root `CLAUDE.md` (the `friendly-reminder/` row + vault keys note)
- Update: `friendly-reminder/.notes/daily_log.md` and `friendly-reminder/.notes/00_INDEX.md`

- [ ] **Step 1: Document the webhook in `friendly-reminder/README.md`**

Add a "LINE slip auto-pay" section: webhook URL `https://fixhardez.synology.me:15066/webhook/line`; behavior (1 outstanding → auto attach+pay, multiple → bot asks for the name); vault key `stacks.friendly_reminder.line.channel_secret`; the "outstanding = due ≤ this month & unpaid" rule.

- [ ] **Step 2: Update root `CLAUDE.md`**

In the `friendly-reminder/` table row, append: "LINE webhook `/webhook/line` (public via DSM RP `:15066`) — โพสต์สลิปในกลุ่ม → แนบสลิป+mark paid อัตโนมัติ (งวดเดียวค้าง auto, หลายงวดถาม)". Add `channel_secret` to the listed vault keys.

- [ ] **Step 3: Deploy**

```bash
./scripts/deploy.sh -s friendly-reminder -y
```
(`--force-recreate` from the earlier fix ensures nginx re-reads the new config and the app rebuilds.)

- [ ] **Step 4: MANUAL — LINE Official Account Manager (user)**

In the LINE OA for this channel:
- **Messaging API → Use webhook: ON**, Webhook URL = `https://fixhardez.synology.me:15066/webhook/line`, click **Verify** (expect 200).
- **Response settings → Auto-reply: OFF**, Greeting: optional. (If auto-reply is on, the OA eats messages and your webhook never fires.)
- Ensure the bot is a member of the target group (`FRIENDLY_LINE_GROUP_ID`).

- [ ] **Step 5: Smoke test on NAS**

- Post a slip image in the group with exactly one outstanding payment → expect "✅ บันทึกสลิป + จ่ายแล้ว …" and the payment shows paid + slip thumbnail in the web UI.
- With two outstanding, post an image → expect the "พิมพ์ชื่อรายการ" prompt; reply with one name → expect the confirm and that payment paid.
- Tail logs if needed: `ssh nas "echo '<sudo>' | sudo -S /usr/local/bin/docker logs --tail 40 friendly-reminder"`.

- [ ] **Step 6: Update `.notes` and commit docs**

```bash
git add friendly-reminder/README.md CLAUDE.md friendly-reminder/.notes/
git commit -m "docs(friendly-reminder): document LINE slip webhook + mobile redesign"
```

---

## Self-Review

**Spec coverage:**
- "slip column invisible on mobile / redesign" → Task 5. ✓
- "prettier app" → Task 5 Step 3. ✓
- "slip posted in group → attach + mark paid immediately" → Tasks 1–4 (logic, webhook, nginx, secret). ✓
- "1 outstanding auto / multiple ask" (user decision) → Task 1 `decide`. ✓
- Public HTTPS ingress (user provisioned `:15066`) → Task 3 + Task 6 Step 4. ✓

**Edge cases baked in:** outstanding defined as due ≤ this month & unpaid (Global Constraints + Task 2 `_outstanding_payments`); content URL expiry → download on arrival (Task 2); signature mandatory + group gate (Task 2); idempotent attach/pay + per-event try/except (Task 2); pending TTL + restart ceiling (Task 1 ponytail comment).

**Manual/user items flagged:** channel secret value (Task 4), LINE OA webhook-on/auto-reply-off (Task 6 Step 4).

**Type consistency:** `Decision.slip_path` carries the slip basename end-to-end; `_apply_attach_pay(conn, payment_id, slip_filename)` stores the basename, served by the existing `/api/slips/{filename}`. `decide` signature identical across Task 1 definition and Task 2 call site.
