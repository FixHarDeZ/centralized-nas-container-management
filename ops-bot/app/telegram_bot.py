# ops-bot/app/telegram_bot.py
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🔵",
}

SEVERITY_THAI = {
    "critical": "วิกฤต",
    "warning": "เตือน",
    "info": "ข้อมูล",
}


def format_report_message(service_name: str, report) -> str:
    emoji = SEVERITY_EMOJI.get(report.severity, "⚪")
    thai = SEVERITY_THAI.get(report.severity, report.severity)
    lines = [
        f"📋 **ผลการวินิจฉัย — {service_name}**",
        f"{emoji} ระดับ: {thai}\n",
        f"**สรุปสาเหตุ:** {report.summary}",
    ]
    if report.evidence:
        rows = "\n".join(f"{e.get('factor','')}: {e.get('value','')}" for e in report.evidence)
        lines.append(f"\n**ปัจจัย:**\n```\n{rows}\n```")
    if report.machine_status:
        lines.append(f"\n**สถานะเครื่อง:** {report.machine_status}")
    if report.fix_options:
        lines.append("\n**ขั้นตอนแก้ (รออนุมัติจากคุณ):**")
        for o in report.fix_options:
            star = "⭐ " if o.recommended else ""
            lines.append(f"{star}**{o.title}** — {o.detail}")
            if o.commands:
                cmds = "\n".join(o.commands)
                lines.append(f"```\n{cmds}\n```")
    if report.truncated:
        lines.append("\n⚠️ วิเคราะห์ไม่ครบ (ถึงเพดานรอบ)")
    return "\n".join(lines)


class TelegramBot:
    def __init__(self):
        cfg = get_config()
        self.token = cfg.telegram_bot_token
        self.chat_id = cfg.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send_message(self, text: str, reply_markup: Optional[dict] = None) -> dict:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
            if resp.status_code != 200:
                logger.error(f"Telegram send failed ({resp.status_code}), retrying without Markdown")
                payload.pop("parse_mode", None)
                resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
            if resp.status_code != 200:
                logger.error(f"Telegram send failed again: {resp.status_code} — {resp.text[:200]}")
                return {"ok": False}
            return resp.json()

    async def send_incident_report(self, service_name: str, report, incident_id: int) -> None:
        msg = format_report_message(service_name, report)
        keyboard = {"inline_keyboard": [[{"text": "📋 ดู Logs เพิ่มเติม", "callback_data": f"logs:{incident_id}"}]]}
        await self.send_message(msg, reply_markup=keyboard)

    async def send_fix_confirmation(
        self, incident_id: int, action_type: str, result: str, success: bool
    ) -> None:
        status = "✅ สำเร็จ" if success else "❌ ล้มเหลว"
        msg = f"{status} — {action_type}\n\n```\n{result[:500]}\n```"
        await self.send_message(msg)

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.base_url}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
            )

    async def send_recovery_notification(self, service_name: str) -> None:
        msg = (
            f"🟢 **{service_name} กลับมาทำงานปกติแล้ว!**\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await self.send_message(msg)


_telegram_bot: Optional[TelegramBot] = None


def get_telegram_bot() -> TelegramBot:
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = TelegramBot()
    return _telegram_bot
