"""Hit & Run auto-fix: ask on Telegram, re-add the .torrent, report when cleared.

A file goes stale on myhr.php when its Download Station task is gone — the tracker
stops seeing us and the 48h seed requirement never completes. Dropping the .torrent
back into the watch folder (already mounted at /downloads) makes DSM pick it up.

Nothing downloads without an explicit Telegram confirm: re-adding a task costs
bandwidth and may re-download the payload, so it is never automatic.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import config
import db
import hr
import hr_delete
import line_notify
import scraper
import telegram_notify

_PROMPT_TTL_H = 12.0  # a button older than this is stale — state has moved on
_MAX_PROMPTS_PER_ROUND = 3
_TZ = ZoneInfo(config.TZ)
_FIX_GRACE_H = 24.0  # DS should have picked the .torrent up long before this


def _fmt(v) -> str:
    return "?" if v is None else f"{v:.1f}"


def _older_than(ts: str | None, hours: float) -> bool:
    try:
        return datetime.fromisoformat(ts) < datetime.now(_TZ) - timedelta(hours=hours)
    except (TypeError, ValueError):
        return False


def _detail_url(site_id: str) -> str:
    return f"{config.SITE_BASE_URL}/details.php?id={site_id}"


async def scan_and_prompt(rows: list[dict], settings: dict) -> int:
    """Ask about stale warned files. Returns how many prompts were sent."""
    if settings.get("hr_autofix_enabled", "0") != "1":
        return 0
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return 0

    for expired in db.hr_fix_expire_pending(_PROMPT_TTL_H):
        print(f"[hr_fix] prompt expired for {expired}")

    stale_h = float(settings.get("hr_fix_stale_hours") or 24)
    sent = 0
    for row in hr.fix_candidates(rows, stale_h, limit=_MAX_PROMPTS_PER_ROUND * 2):
        prev = db.hr_fix_get(row["site_id"])
        # pending = still waiting on an answer, fixed = already re-added and not yet
        # seen by the tracker, skipped = user said no. None of those re-ask.
        if prev and prev["status"] in ("pending", "fixed", "skipped"):
            continue
        badge_line = f"{row['badges']}\n" if row.get("badges") else ""
        text = (
            f"🛠 H&R auto-fix?\n\n"
            f"🎬 {row['title'][:80]}\n"
            f"{badge_line}"
            f"⏳ seed {_fmt(row['seeded_h'])}/{_fmt(row['target_h'])} ชม."
            f" · ขาดอีก {_fmt(row['remaining_h'])} ชม.\n"
            f"📡 ระบบเห็นล่าสุด {_fmt(row['last_seen_h'])} ชม. ที่แล้ว (งานใน DS น่าจะหายไปแล้ว)\n"
            f"⌛ เหลือเวลา {_fmt(row['slack_h'])} ชม. (ครบกำหนด {row['deadline']})\n\n"
            f"โหลด .torrent ใส่ watch folder ให้ Download Station seed ต่อไหม?"
        )
        message_id = await telegram_notify.send_buttons(
            text,
            [[
                {"text": "✅ fix เลย", "callback_data": f"hrfix:y:{row['site_id']}"},
                {"text": "❌ ข้าม", "callback_data": f"hrfix:n:{row['site_id']}"},
            ]],
        )
        if message_id is None:
            continue
        db.hr_fix_add_pending(row["site_id"], row["title"], message_id)
        sent += 1
        if sent >= _MAX_PROMPTS_PER_ROUND:
            break
    if sent:
        print(f"[hr_fix] {sent} auto-fix prompt(s) sent")
    return sent


async def apply_fix(site_id: str) -> tuple[bool, str]:
    """Re-check the row, then write its .torrent into the watch folder."""
    await scraper.relogin()
    html = await scraper.fetch_hr_html()
    if not html:
        return False, "ดึง myhr.php ไม่สำเร็จ"

    row = next((r for r in hr.parse_hr(html) if r["site_id"] == site_id), None)
    if row is None:
        return False, "ไม่เจอรายการนี้ใน myhr.php แล้ว"
    if row.get("seeding_now"):
        return False, "ตอนนี้ระบบเห็น client กำลัง seed อยู่แล้ว ไม่ต้อง fix"
    if hr.is_cleared(row):
        return False, "seed ครบแล้ว ไม่ต้อง fix"

    data = await scraper.fetch_torrent_bytes("", _detail_url(site_id))
    if not data:
        return False, "โหลดไฟล์ .torrent ไม่สำเร็จ"

    dest = Path(config.NAS_DOWNLOADS_DIR) / db.torrent_filename(row["title"])
    try:
        dest.write_bytes(data)
    except OSError as e:
        # An escaping OSError left the row 'pending', so the poller re-asked and
        # re-failed every cycle with nothing said in Telegram. Report it instead.
        return False, f"เขียนไฟล์ลง watch folder ไม่สำเร็จ: {e}"
    return True, f"{dest.name} ({len(data):,} bytes)"


async def check_cleared(rows: list[dict], settings: dict | None = None) -> int:
    """Notify LINE+Telegram for fixed files that have now seeded their full 48h.

    Only rows still present on the page count — parse_hr returns [] when the table
    is missing, and a disappearing row is not proof of success.
    """
    if not rows:
        return 0
    by_id = {r["site_id"]: r for r in rows}
    done = 0
    for fix in db.hr_fix_by_status("fixed"):
        row = by_id.get(fix["site_id"])
        if row is None:
            continue
        if not hr.is_cleared(row):
            # DS never picked it up (watch folder off, task errored). Left as
            # "fixed" the row would never be re-prompted and would drift to hit.
            if not row.get("seeding_now") and _older_than(fix["decided_at"], _FIX_GRACE_H):
                db.hr_fix_set_status(fix["site_id"], "stalled", "DS ไม่รับงานภายใน 24 ชม.")
                print(f"[hr_fix] {fix['site_id']} stalled — will re-prompt")
            continue
        body = (
            f"✅ พ้น Hit & Run แล้ว\n\n"
            f"🎬 {row['title'][:80]}\n"
            f"⏳ seed {_fmt(row['seeded_h'])}/{_fmt(row['target_h'])} ชม. ครบตามกำหนด"
        )
        if config.LINE_ACCESS_TOKEN and config.LINE_USER_ID:
            await line_notify.notify_hr(body)
        if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
            await telegram_notify.notify_hr(body)
        db.hr_fix_set_status(fix["site_id"], "cleared")
        if hr_delete.enabled(settings or {}):
            await hr_delete.prompt_delete(fix["site_id"], fix["title"])
        done += 1
    if done:
        print(f"[hr_fix] {done} file(s) cleared H&R")
    return done


_CLEAR_TOLERANCE_H = 2.0  # how far short a last sighting may be and still count as done

# Statuses that have not yet passed the "cleared" gate. Anything else (cleared,
# del_*, deleted) has already been offered for deletion and must not be re-asked.
_PRE_CLEAR = ("pending", "fixed", "stalled", "failed", "skipped", "expired")


async def check_vanished(rows: list[dict], settings: dict | None = None) -> int:
    """Handle rows that dropped off myhr.php, then re-snapshot the page.

    check_cleared only ever sees a file that is still listed at 48/48, which the
    twice-a-day read almost never catches — bearbit removes the row as soon as the
    obligation is met. This closes that gap for every listed file, not just the
    auto-fixed ones, using the last sighting as proof (hr.was_cleared).
    """
    if not rows:
        # parse_hr returns [] for a failed fetch too — that is not 20 files clearing.
        return 0
    settings = settings or {}
    present = {r["site_id"] for r in rows if r["site_id"]}
    done = 0
    for snap in db.hr_seen_vanished(present):
        site_id = snap["site_id"]
        if not hr.was_cleared(snap, _CLEAR_TOLERANCE_H):
            db.hr_seen_forget(site_id)
            print(
                f"[hr_fix] {site_id} หายจากหน้า myhr แต่ครั้งสุดท้ายยังขาด "
                f"{_fmt(snap['remaining_h'])} ชม. ({snap['state']}) — ไม่ถือว่าครบ"
            )
            continue

        fix = db.hr_fix_get(site_id)
        # "cleared" stays retriable: the row only survives in hr_seen when a previous
        # round marked it cleared but could not send the prompt.
        if fix and fix["status"] not in _PRE_CLEAR + ("cleared",):
            db.hr_seen_forget(site_id)
            continue
        title = snap["title"] or (fix["title"] if fix else site_id)
        if fix and fix["status"] in ("fixed", "stalled"):
            # The user pressed a button for this one, so close the loop on it.
            body = (
                f"✅ พ้น Hit & Run แล้ว\n\n"
                f"🎬 {title[:80]}\n"
                f"⏳ seed {_fmt(snap['seeded_h'])}/{_fmt(snap['target_h'])} ชม."
                f" แล้วหลุดจากหน้า myhr"
            )
            if config.LINE_ACCESS_TOKEN and config.LINE_USER_ID:
                await line_notify.notify_hr(body)
            if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
                await telegram_notify.notify_hr(body)
        if fix:
            db.hr_fix_set_status(site_id, "cleared")
        else:
            db.hr_fix_add_cleared(site_id, title)
        if hr_delete.enabled(settings) and not await hr_delete.prompt_delete(site_id, title):
            # Telegram refused the send. Keep the snapshot so the next round asks
            # again — dropping it here would lose the file the way check_cleared did.
            print(f"[hr_fix] {site_id} ส่งคำถามลบไม่สำเร็จ — เก็บ snapshot ไว้ลองใหม่รอบหน้า")
            continue
        db.hr_seen_forget(site_id)
        done += 1
    db.hr_seen_snapshot(rows)
    if done:
        print(f"[hr_fix] {done} file(s) cleared H&R by dropping off the page")
    return done


async def _handle_callback(cb: dict):
    data = cb.get("data") or ""
    cb_id = cb.get("id") or ""
    message = cb.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    message_id = message.get("message_id")

    # This flow writes files to the NAS — only the configured chat may drive it.
    if chat_id != str(config.TELEGRAM_CHAT_ID):
        await telegram_notify.answer_callback(cb_id, "ไม่ได้รับอนุญาต")
        print(f"[hr_fix] callback from unexpected chat {chat_id} ignored")
        return
    if data.startswith("hrdel:"):
        _, action, site_id = data.split(":", 2)
        await hr_delete.handle_callback(action, site_id, cb_id, message_id)
        return
    if not data.startswith("hrfix:"):
        await telegram_notify.answer_callback(cb_id)
        return

    _, action, site_id = data.split(":", 2)
    fix = db.hr_fix_get(site_id)
    if fix is None or fix["status"] != "pending":
        state = fix["status"] if fix else "ไม่พบ"
        await telegram_notify.answer_callback(cb_id, f"ปุ่มนี้ใช้ไปแล้ว ({state})")
        return

    if action == "n":
        db.hr_fix_set_status(site_id, "skipped")
        await telegram_notify.answer_callback(cb_id, "ข้ามแล้ว")
        if message_id:
            await telegram_notify.edit_message(message_id, f"❌ ข้าม — {fix['title'][:80]}")
        return

    await telegram_notify.answer_callback(cb_id, "กำลังโหลด .torrent ...")
    ok, detail = await apply_fix(site_id)
    db.hr_fix_set_status(site_id, "fixed" if ok else "failed", detail)
    icon = "✅" if ok else "⚠️"
    head = "ส่งเข้า watch folder แล้ว" if ok else "fix ไม่สำเร็จ"
    if message_id:
        await telegram_notify.edit_message(
            message_id,
            f"{icon} {head} — {fix['title'][:80]}\n{detail}",
        )
    print(f"[hr_fix] apply {site_id}: ok={ok} {detail}")


async def poll_loop():
    """Long-poll Telegram for button presses. Started from the app lifespan."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        print("[hr_fix] telegram not configured — poller off")
        return
    telegram_notify.POLLER_ACTIVE = True
    print("[hr_fix] telegram callback poller started")
    while True:
        try:
            offset = int(db.get_meta("tg_last_update_id") or 0)
            updates = await telegram_notify.poll_callbacks(offset + 1 if offset else 0)
            for u in updates:
                db.set_meta("tg_last_update_id", str(u["update_id"]))
                if "callback_query" in u:
                    await _handle_callback(u["callback_query"])
        except asyncio.CancelledError:
            telegram_notify.POLLER_ACTIVE = False
            raise
        except Exception as e:
            print(f"[hr_fix] poll error: {e}")
            await asyncio.sleep(15)


if __name__ == "__main__":
    # check_vanished against a temp DB, with Telegram/LINE stubbed out. Covers the
    # branching that has no other coverage: the empty-page guard, the ≤2h tolerance,
    # the hit exclusion, and the retry a failed Telegram send has to leave behind.
    import tempfile

    # config is already imported by the time this runs, so DATA_DIR is settled —
    # point the connection helper at a throwaway file instead.
    config.DB_PATH = tempfile.mkdtemp() + "/selfcheck.db"
    db.init_db()

    _prompts: list[str] = []
    _notices: list[str] = []

    async def _fake_buttons(text, kb):
        _prompts.append(text)
        return 1

    async def _fake_notify(body):
        _notices.append(body)

    async def _dead_buttons(text, kb):
        return None

    telegram_notify.send_buttons = _fake_buttons
    telegram_notify.notify_hr = _fake_notify
    line_notify.notify_hr = _fake_notify
    hr_delete.enabled = lambda s: True
    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID = "t", "c"
    config.LINE_ACCESS_TOKEN, config.LINE_USER_ID = "", ""

    def _row(site_id, remaining, state="ok"):
        return {
            "site_id": site_id,
            "title": f"หนัง {site_id}",
            "seeded_h": 48.0 - remaining,
            "target_h": 48.0,
            "remaining_h": remaining,
            "state": state,
        }

    async def _selfcheck():
        page = [_row("1", 1.5), _row("2", 20.0), _row("3", 0.0), _row("4", 5.0, "hit")]
        assert await check_vanished(page, {}) == 0  # first pass only snapshots
        assert _prompts == []
        assert await check_vanished([], {}) == 0  # failed fetch is not "all cleared"
        assert _prompts == []

        assert await check_vanished([_row("3", 0.0)], {}) == 1
        assert len(_prompts) == 1 and "หนัง 1" in _prompts[0]
        assert db.hr_fix_get("1")["status"] == "del_asked"
        assert db.hr_fix_get("2") is None and db.hr_fix_get("4") is None
        assert _notices == []  # no "cleared" push for a file that skipped auto-fix

        db.hr_fix_add_pending("9", "หนัง 9", 5)
        db.hr_fix_set_status("9", "fixed", "x.torrent")
        await check_vanished([_row("9", 0.5), _row("3", 0.0)], {})
        assert await check_vanished([_row("3", 0.0)], {}) == 1
        assert db.hr_fix_get("9")["status"] == "del_asked"
        assert len(_notices) == 1 and "พ้น Hit & Run" in _notices[0]

        db.hr_seen_snapshot([_row("7", 0.0)])
        db.hr_fix_add_cleared("7", "หนัง 7")
        db.hr_fix_set_status("7", "deleted", "ok")
        _before = len(_prompts)
        assert await check_vanished([_row("3", 0.0)], {}) == 0
        assert len(_prompts) == _before

        telegram_notify.send_buttons = _dead_buttons
        db.hr_seen_snapshot([_row("5", 0.0)])
        assert await check_vanished([_row("3", 0.0)], {}) == 0
        assert db.hr_fix_get("5")["status"] == "cleared"  # snapshot kept for a retry
        telegram_notify.send_buttons = _fake_buttons
        assert await check_vanished([_row("3", 0.0)], {}) == 1
        assert db.hr_fix_get("5")["status"] == "del_asked"
        assert await check_vanished([_row("3", 0.0)], {}) == 0  # snapshot dropped now

        print(f"hr_fix self-check OK: {len(_prompts)} prompt(s), {len(_notices)} notice(s)")

    asyncio.run(_selfcheck())
