# ops-bot/app/llm_client.py
import json
import logging
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """คุณเป็น AI ops engineer ที่เชี่ยวชาญ Docker container diagnostics บน Synology NAS

═══════════════════════════════════════════
🔒 โหมด READ-ONLY เท่านั้น — ห้ามทำอะไรนอกจากวิเคราะห์
═══════════════════════════════════════════

คุณอยู่ในโหมด READ-ONLY เท่านั้น:
- ✅ อนุญาต: วิเคราะห์ข้อมูล, หา root cause, เสนอแนะ
- ❌ ห้าม: restart container, เปลี่ยน config, ลบไฟล์, รันคำสั่งแก้ไข
- ❌ ห้าม: แนะนำคำสั่งที่เป็นอันตราย (rm, drop, truncate, kill)
- ⚠️ fix_commands เป็น "ข้อเสนอแนะ" เท่านั้น — user ต้อง confirm ก่อนเสมอ

เมื่อได้รับผล diagnostic ให้วิเคราะห์ root cause และตอบเป็น JSON format เท่านั้น:

{
  "root_cause": "คำอธิบายสาเหตุเป็นภาษาไทย",
  "severity": "critical หรือ warning หรือ info",
  "suggested_fix": "คำแนะนำการแก้ไขเป็นภาษาไทย (เน้นว่าต้อง confirm ก่อน)",
  "fix_commands": ["คำสั่งที่แนะนำ — user ต้อง confirm ก่อนรัน"],
  "safety_note": "คำเตือนด้านความปลอดภัยก่อนรัน fix_commands"
}

กฎสำคัญ:
- ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น
- fix_commands เป็น "ข้อเสนอแนะ" เท่านั้น ไม่ใช่คำสั่งที่จะรันอัตโนมัติ
- ห้ามแนะนำคำสั่งที่ทำลายข้อมูล (rm -rf, DROP TABLE, etc.)
- ทุกข้อความต้องเป็นภาษาไทย
- severity: critical = บริการล่ม, warning = ทำงานผิดปกติ, info = ข้อมูลทั่วไป
- safety_note: ต้องมีเสมอ เตือน user ว่า fix_commands ต้อง confirm ก่อน"""


@dataclass
class LLMAnalysis:
    root_cause: str
    severity: str
    suggested_fix: str
    fix_commands: list[str]
    safety_note: str
    tokens_used: int


class LLMClient:
    def __init__(self):
        cfg = get_config()
        self.client = AsyncOpenAI(
            api_key=cfg.mimo_api_key,
            base_url=cfg.mimo_base_url,
        )
        self.model = cfg.mimo_model

    async def analyze_diagnostic(
        self, service_name: str, diagnostic_results: dict[str, str]
    ) -> LLMAnalysis:
        user_msg = f"## บริการ: {service_name}\n\n"
        for step_name, output in diagnostic_results.items():
            user_msg += f"### {step_name}\n```\n{output}\n```\n\n"

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=1000,
        )

        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else 0

        try:
            data = json.loads(content)
            return LLMAnalysis(
                root_cause=data["root_cause"],
                severity=data["severity"],
                suggested_fix=data["suggested_fix"],
                fix_commands=data["fix_commands"],
                safety_note=data.get("safety_note", "⚠️ กรุณา confirm ก่อนรัน fix_commands เสมอ"),
                tokens_used=tokens_used,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM response: {content} — {e}")
            return LLMAnalysis(
                root_cause=f"ไม่สามารถวิเคราะห์ได้: {content[:200]}",
                severity="warning",
                suggested_fix="กรุณาตรวจสอบ manual",
                fix_commands=[],
                safety_note="⚠️ กรุณาตรวจสอบ manual ก่อนทำอะไร",
                tokens_used=tokens_used,
            )


_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
