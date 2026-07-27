"""Post-H&R cleanup: offer to delete a cleared torrent, asking twice.

Once a file has served its 48h it is safe to remove, but removal is permanent —
FileStation.Delete does not use #recycle — so the flow is deliberately two hops:

    cleared → del_asked → del_confirm → deleted

The first button only *resolves* what would be deleted (DS task + the real path
on disk) and shows it back. Nothing is touched until the second button, so the
user confirms against a real path rather than a torrent title.

Off unless `hr_delete_enabled` is "1" and DSM credentials are set.
"""

import json

import config
import db
import dsm
import telegram_notify


def _fmt_size(n) -> str:
    if not isinstance(n, (int, float)):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def enabled(settings: dict) -> bool:
    return settings.get("hr_delete_enabled", "0") == "1" and dsm.configured()


async def prompt_delete(site_id: str, title: str) -> bool:
    """Ask whether to delete a just-cleared torrent. First of two confirmations."""
    text = (
        f"🧹 พ้น H&R แล้ว — ลบทิ้งไหม?\n\n"
        f"🎬 {title[:80]}\n\n"
        f"กดแล้วยังไม่ลบ ระบบจะไปหา task ใน Download Station "
        f"กับ path ไฟล์จริงมาให้ยืนยันอีกรอบก่อน"
    )
    message_id = await telegram_notify.send_buttons(
        text,
        [[
            {"text": "🗑 ขอดูก่อนลบ", "callback_data": f"hrdel:ask:{site_id}"},
            {"text": "❌ เก็บไว้", "callback_data": f"hrdel:no:{site_id}"},
        ]],
    )
    if message_id is None:
        return False
    db.hr_fix_set_status(site_id, "del_asked")
    return True


async def _resolve(site_id: str, title: str) -> tuple[dict | None, str]:
    """Find the DS task and stat its payload. Returns (target, error message)."""
    torrent_name = db.torrent_filename(title)
    try:
        async with dsm.Dsm() as d:
            task = dsm.find_task(await d.list_tasks(), title, torrent_name)
            if task is None:
                return None, "ไม่เจอ task นี้ใน Download Station แล้ว (อาจถูกลบไปก่อนหน้า)"
            path = dsm.task_payload_path(task)
            info = await d.stat(path)
    except dsm.DsmError as e:
        return None, f"DSM error: {e}"
    if info is None or not info.get("real_path"):
        # Never guess: a multi-file torrent with no wrapper folder puts its files
        # straight into destination, and deleting destination would take the lot.
        return None, f"หา path ไฟล์จริงไม่เจอ ({path}) — ไม่ลบ"
    return {
        "task_id": task["id"],
        "task_title": task.get("title") or "",
        "path": path,
        "real_path": info["real_path"],
        "size": info.get("size"),
        "isdir": bool(info.get("isdir")),
    }, ""


async def _do_delete(target: dict) -> tuple[bool, str]:
    """Delete the DS task first, then the payload. Task-first avoids DS rewriting it."""
    try:
        async with dsm.Dsm() as d:
            # The confirm button can sit in Telegram for weeks. Re-stat so the
            # second press is a check, not a replay of a stale snapshot.
            info = await d.stat(target["path"])
            if (
                info is None
                or info.get("real_path") != target["real_path"]
                or info.get("size") != target["size"]
            ):
                return False, "ไฟล์เปลี่ยนไปจากตอนยืนยัน — ไม่ลบ"
            await d.delete_task(target["task_id"])
            try:
                await d.delete_path(target["path"])
            except dsm.DsmError as e:
                # Half-done is the one outcome the bot cannot retry: pressing the
                # button again re-resolves through a task that no longer exists.
                return False, f"ลบ task ใน DS แล้ว แต่ลบไฟล์ไม่สำเร็จ — ต้องลบเองที่ {target['real_path']}\nDSM error: {e}"
    except dsm.DsmError as e:
        return False, f"DSM error: {e}"
    return True, f"ลบแล้ว: {target['real_path']}"


async def handle_callback(action: str, site_id: str, cb_id: str, message_id: int | None):
    """Route a `hrdel:<action>:<site_id>` press. Called from hr_fix._handle_callback."""
    fix = db.hr_fix_get(site_id)
    if fix is None:
        await telegram_notify.answer_callback(cb_id, "ไม่พบรายการนี้")
        return

    if action == "no":
        if fix["status"] not in ("cleared", "del_asked", "del_confirm"):
            await telegram_notify.answer_callback(cb_id, f"ปุ่มนี้ใช้ไปแล้ว ({fix['status']})")
            return
        db.hr_fix_set_status(site_id, "del_skipped")
        await telegram_notify.answer_callback(cb_id, "เก็บไฟล์ไว้")
        if message_id:
            await telegram_notify.edit_message(message_id, f"📦 เก็บไว้ — {fix['title'][:80]}")
        return

    if action == "ask":
        if fix["status"] != "del_asked":
            await telegram_notify.answer_callback(cb_id, f"ปุ่มนี้ใช้ไปแล้ว ({fix['status']})")
            return
        await telegram_notify.answer_callback(cb_id, "กำลังหา task ใน DSM ...")
        target, err = await _resolve(site_id, fix["title"])
        if target is None:
            db.hr_fix_set_status(site_id, "del_failed", err)
            if message_id:
                await telegram_notify.edit_message(
                    message_id, f"⚠️ ลบไม่ได้ — {fix['title'][:80]}\n{err}"
                )
            return
        db.hr_fix_set_status(site_id, "del_confirm", json.dumps(target, ensure_ascii=False))
        kind = "โฟลเดอร์" if target["isdir"] else "ไฟล์"
        await telegram_notify.send_buttons(
            f"⚠️ ยืนยันอีกครั้ง — ลบถาวร ไม่เข้าถังขยะ\n\n"
            f"🎬 {target['task_title'][:80]}\n"
            f"📁 {kind}: {target['real_path']}\n"
            f"💾 {_fmt_size(target['size'])}\n"
            f"🧷 DS task: {target['task_id']}\n\n"
            f"ลบทั้ง task และไฟล์จริงเลยไหม?",
            [[
                {"text": "🔥 ยืนยันลบ", "callback_data": f"hrdel:go:{site_id}"},
                {"text": "❌ ยกเลิก", "callback_data": f"hrdel:no:{site_id}"},
            ]],
        )
        return

    if action == "go":
        if fix["status"] != "del_confirm":
            await telegram_notify.answer_callback(cb_id, f"ปุ่มนี้ใช้ไปแล้ว ({fix['status']})")
            return
        try:
            target = json.loads(fix["note"] or "{}")
        except ValueError:
            target = {}
        if not target.get("task_id") or not target.get("path"):
            db.hr_fix_set_status(site_id, "del_failed", "ข้อมูลเป้าหมายหาย")
            await telegram_notify.answer_callback(cb_id, "ข้อมูลเป้าหมายหาย ไม่ลบ")
            return
        await telegram_notify.answer_callback(cb_id, "กำลังลบ ...")
        ok, detail = await _do_delete(target)
        db.hr_fix_set_status(site_id, "deleted" if ok else "del_failed", detail)
        if message_id:
            await telegram_notify.edit_message(
                message_id, f"{'🗑' if ok else '⚠️'} {detail}"
            )
        print(f"[hr_delete] {site_id}: ok={ok} {detail}")
        return

    await telegram_notify.answer_callback(cb_id)
