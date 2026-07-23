# ops-bot/app/llm_client.py
import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import get_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """คุณเป็น AI ops engineer ที่เชี่ยวชาญ Docker container diagnostics บน Synology NAS

เมื่อได้รับผล diagnostic ให้วิเคราะห์ root cause และตอบเป็น JSON format เท่านั้น:

{
  "root_cause": "คำอธิบายสาเหตุเป็นภาษาไทย",
  "severity": "critical หรือ warning หรือ info",
  "suggested_fix": "คำแนะนำการแก้ไขเป็นภาษาไทย",
  "fix_commands": ["คำสั่งที่ใช้แก้ไข 1", "คำสั่งที่ใช้แก้ไข 2"]
}

กฎสำคัญ:
- ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น
- fix_commands ต้องเป็นคำสั่งที่รันได้จริง
- ทุกข้อความต้องเป็นภาษาไทย
- severity: critical = บริการล่ม, warning = ทำงานผิดปกติ, info = ข้อมูลทั่วไป"""


@dataclass
class LLMAnalysis:
    root_cause: str
    severity: str
    suggested_fix: str
    fix_commands: list[str]
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
                tokens_used=tokens_used,
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM response: {content} — {e}")
            return LLMAnalysis(
                root_cause=f"ไม่สามารถวิเคราะห์ได้: {content[:200]}",
                severity="warning",
                suggested_fix="กรุณาตรวจสอบ manual",
                fix_commands=[],
                tokens_used=tokens_used,
            )


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
