"""Post-H&R cleanup: offer to delete a cleared torrent, asking twice.

Once a file has served its 48h it is safe to remove, but removal is permanent —
FileStation.Delete does not use #recycle — so the flow is deliberately two hops:

    cleared → del_asked → del_confirm → deleted
                                      ↘ del_task_only  (task gone, file kept)

The first button only *resolves* what would be deleted (DS task + the real path
on disk) and shows it back. Nothing is touched until the second button, so the
user confirms against a real path rather than a torrent title.

The second step also offers task-only removal: DownloadStation delete runs with
force_complete=false and never touches the payload, so dropping the task alone
just stops seeding and leaves the file. That is the only offer when the payload
path cannot be resolved — the case where deleting files would be a guess.

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
    """Find the DS task and stat its payload.

    Returns (target, warning). A target with `real_path` = None is still usable —
    the task is there, only the file half is unknown — so the caller can offer
    task-only removal. target is None just when there is nothing to act on.
    """
    torrent_name = db.torrent_filename(title)
    stat_err = ""
    try:
        async with dsm.Dsm() as d:
            task = dsm.find_task(await d.list_tasks(), title, torrent_name)
            if task is None:
                return None, "ไม่เจอ task นี้ใน Download Station แล้ว (อาจถูกลบไปก่อนหน้า)"
            path = dsm.task_payload_path(task)
            try:
                info = await d.stat(path)
            except dsm.DsmError as e:
                # A stat that blows up leaves us exactly where a stat that returns
                # nothing does: task in hand, file half unknown. Dead-ending at
                # del_failed here would bury the row for good over one DSM blip.
                info, stat_err = None, f" (stat ล้มเหลว: {e})"
    except dsm.DsmError as e:
        return None, f"DSM error: {e}"
    target = {
        "task_id": task["id"],
        "task_title": task.get("title") or "",
        "path": path,
        "real_path": (info or {}).get("real_path"),
        "size": (info or {}).get("size"),
        "isdir": bool((info or {}).get("isdir")),
    }
    if not target["real_path"]:
        # Never guess: a multi-file torrent with no wrapper folder puts its files
        # straight into destination, and deleting destination would take the lot.
        return target, f"⚠️ หา path ไฟล์จริงไม่เจอ ({path}){stat_err} — ลบไฟล์ไม่ได้ ลบได้แค่ task"
    return target, ""


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


async def _delete_task_only(target: dict) -> tuple[bool, str]:
    """Drop the DS task and keep the payload — stops seeding, deletes nothing."""
    try:
        async with dsm.Dsm() as d:
            await d.delete_task(target["task_id"])
    except dsm.DsmError as e:
        return False, f"DSM error: {e}"
    where = target["real_path"] or target["path"]
    return True, f"ลบ task ใน Download Station แล้ว — ไฟล์ยังอยู่ที่ {where}"


async def _finish(site_id: str, status: str, detail: str, message_id: int | None, icon: str):
    """Close a delete out: record it, kill the buttons, and push a real message.

    editMessageText makes no sound on the phone, so the edit alone read as "nothing
    happened". The edit keeps the thread honest; the push is what gets noticed.
    """
    db.hr_fix_set_status(site_id, status, detail)
    if message_id:
        await telegram_notify.edit_message(message_id, f"{icon} {detail}")
    await telegram_notify.notify_hr(f"{icon} {detail}")


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
        target, warn = await _resolve(site_id, fix["title"])
        if target is None:
            await _finish(site_id, "del_failed", f"ลบไม่ได้ — {fix['title'][:80]}\n{warn}", message_id, "⚠️")
            return
        db.hr_fix_set_status(site_id, "del_confirm", json.dumps(target, ensure_ascii=False))
        # Stage 1 keeps its "ขอดูก่อนลบ" buttons otherwise, and after the delete goes
        # through the old live prompt reads as if nothing ever happened.
        if message_id:
            await telegram_notify.edit_message(
                message_id, f"🔎 หา task เจอแล้ว — {fix['title'][:80]}\nดูข้อความยืนยันด้านล่าง"
            )
        kind = "โฟลเดอร์" if target["isdir"] else "ไฟล์"
        buttons = [[{"text": "🧷 ลบเฉพาะ task (เก็บไฟล์)", "callback_data": f"hrdel:task:{site_id}"}],
                   [{"text": "❌ ยกเลิก", "callback_data": f"hrdel:no:{site_id}"}]]
        if target["real_path"]:
            body = (
                f"⚠️ ยืนยันอีกครั้ง — ลบถาวร ไม่เข้าถังขยะ\n\n"
                f"🎬 {target['task_title'][:80]}\n"
                f"📁 {kind}: {target['real_path']}\n"
                f"💾 {_fmt_size(target['size'])}\n"
                f"🧷 DS task: {target['task_id']}\n\n"
                f"ลบทั้ง task และไฟล์จริง หรือลบแค่ task?"
            )
            buttons.insert(0, [{"text": "🔥 ลบ task + ไฟล์", "callback_data": f"hrdel:go:{site_id}"}])
        else:
            body = (
                f"🧷 เจอ task แต่ลบไฟล์ไม่ได้\n\n"
                f"🎬 {target['task_title'][:80]}\n"
                f"🧷 DS task: {target['task_id']}\n"
                f"{warn}\n\n"
                f"ลบเฉพาะ task ไหม? (ไฟล์ต้องไปลบเองที่ {target['path']})"
            )
        await telegram_notify.send_buttons(body, buttons)
        return

    if action in ("go", "task"):
        if fix["status"] != "del_confirm":
            await telegram_notify.answer_callback(cb_id, f"ปุ่มนี้ใช้ไปแล้ว ({fix['status']})")
            return
        try:
            target = json.loads(fix["note"] or "{}")
        except ValueError:
            target = {}
        if not target.get("task_id") or not target.get("path"):
            await _finish(site_id, "del_failed", "ข้อมูลเป้าหมายหาย ไม่ลบ", message_id, "⚠️")
            await telegram_notify.answer_callback(cb_id, "ข้อมูลเป้าหมายหาย ไม่ลบ")
            return
        if action == "go" and not target.get("real_path"):
            await telegram_notify.answer_callback(cb_id, "ไม่รู้ path ไฟล์จริง — ลบได้แค่ task")
            return
        await telegram_notify.answer_callback(cb_id, "กำลังลบ ...")
        if action == "go":
            ok, detail = await _do_delete(target)
            status = "deleted" if ok else "del_failed"
        else:
            ok, detail = await _delete_task_only(target)
            status = "del_task_only" if ok else "del_failed"
        await _finish(site_id, status, detail, message_id, "🗑" if ok else "⚠️")
        print(f"[hr_delete] {site_id}: {action} ok={ok} {detail}")
        return

    await telegram_notify.answer_callback(cb_id)


if __name__ == "__main__":
    import asyncio

    _sent, _edits, _pushes, _status, _deleted_tasks = [], [], [], [], []

    async def _fake_buttons(text, kb):
        _sent.append((text, kb))
        return 999

    async def _fake_edit(mid, text):
        _edits.append((mid, text))

    async def _fake_push(text):
        _pushes.append(text)

    async def _fake_answer(cb_id, text=""):
        pass

    telegram_notify.send_buttons = _fake_buttons
    telegram_notify.edit_message = _fake_edit
    telegram_notify.notify_hr = _fake_push
    telegram_notify.answer_callback = _fake_answer
    db.hr_fix_set_status = lambda sid, st, note="": _status.append((st, note))

    _target = {"task_id": "dbid_9", "task_title": "T", "path": "/dl/T.mkv",
               "real_path": "/volume1/dl/T.mkv", "size": 100, "isdir": False}

    def _fix(status, note=""):
        db.hr_fix_get = lambda sid: {"site_id": sid, "title": "T", "status": status, "note": note}

    def _run(action, status, note="", real_path=True):
        _sent.clear(); _edits.clear(); _pushes.clear(); _status.clear()
        _fix(status, note)
        asyncio.run(handle_callback(action, "1", "cb", 5))

    def _codes(kb):
        return [b["callback_data"].split(":")[1] for row in kb for b in row]

    # a stat that raises must still hand back the task half, not dead-end the row
    class _StatBoom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def list_tasks(self): return [{"id": "dbid_9"}]
        async def stat(self, path): raise dsm.DsmError("boom")
    dsm.Dsm = _StatBoom
    dsm.find_task = lambda tasks, title, name: tasks[0]
    dsm.task_payload_path = lambda task: "/dl/T.mkv"
    db.torrent_filename = lambda title: "T.torrent"
    _t, _w = asyncio.run(_resolve("1", "T"))
    assert _t and _t["task_id"] == "dbid_9" and _t["real_path"] is None, (_t, _w)
    assert "stat" in _w, _w

    # resolved path → both delete options, and stage 1 loses its buttons
    async def _ok_resolve(site_id, title):
        return dict(_target), ""
    globals()["_resolve"] = _ok_resolve
    _run("ask", "del_asked")
    assert _codes(_sent[0][1]) == ["go", "task", "no"], _sent[0][1]
    assert _edits and _edits[0][0] == 5, _edits

    # no real path → task-only is the only action offered
    async def _no_path(site_id, title):
        return {**_target, "real_path": None}, "⚠️ หา path ไฟล์จริงไม่เจอ"
    globals()["_resolve"] = _no_path
    _run("ask", "del_asked")
    assert _codes(_sent[0][1]) == ["task", "no"], _sent[0][1]

    # ...and the file-delete callback must refuse that target rather than guess
    _run("go", "del_confirm", json.dumps({**_target, "real_path": None}))
    assert _status == [], _status

    # task-only deletes the task, keeps the file, and pushes a real message
    async def _fake_task_delete(target):
        _deleted_tasks.append(target["task_id"])
        return True, "ลบ task ใน Download Station แล้ว — ไฟล์ยังอยู่"
    globals()["_delete_task_only"] = _fake_task_delete
    _run("task", "del_confirm", json.dumps(_target))
    assert _deleted_tasks == ["dbid_9"], _deleted_tasks
    assert _status == [("del_task_only", "ลบ task ใน Download Station แล้ว — ไฟล์ยังอยู่")], _status
    assert _pushes and _edits, (_pushes, _edits)

    print("hr_delete self-check OK")
