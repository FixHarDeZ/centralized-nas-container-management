# ops-bot/app/llm_client.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from openai import AsyncOpenAI

from app.config import get_config

logger = logging.getLogger(__name__)

MAX_ITERS = 10

SYSTEM_PROMPT = """คุณเป็น AI ops engineer เชี่ยวชาญ Docker diagnostics บน Synology NAS

โหมด READ-ONLY เท่านั้น — ห้าม restart/แก้ config/ลบ. วินิจฉัยด้วยการเรียก tool:

- run_diagnostic(cmd): รันคำสั่ง read-only (docker ps/inspect/logs, df, free, uptime, curl ฯลฯ). ระบบมี whitelist กัน — ถ้าคำสั่งถูก block ให้เปลี่ยนไปใช้คำสั่งอื่น
- note_finding(text): เมื่อเจอเบาะแสสำคัญ ให้เรียกด้วยข้อความไทยสั้นๆ ก่อนตรวจต่อ (เช่น "เจอแล้ว — restart-loop exit 137")
- submit_report(...): เมื่อวินิจฉัยเสร็จ เรียกครั้งเดียวเพื่อส่งรายงานสรุป

ขั้นตอน: ดู container ที่เกี่ยวข้อง → ดู log/inspect หาสาเหตุ → เช็คทรัพยากรเครื่อง → สรุป.
fix_options เป็นข้อเสนอเท่านั้น (ผู้ใช้ต้อง confirm เอง). ทุกข้อความเป็นภาษาไทย."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_diagnostic",
            "description": "รันคำสั่ง diagnostic แบบ read-only บน NAS ผ่าน SSH",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string", "description": "คำสั่ง shell read-only"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_finding",
            "description": "แจ้งเบาะแสสำคัญที่เจอ ให้ผู้ใช้เห็นแบบ real-time",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "ข้อความไทยสั้นๆ"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_report",
            "description": "ส่งรายงานวินิจฉัยฉบับสมบูรณ์ (เรียกครั้งเดียวตอนจบ)",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"factor": {"type": "string"}, "value": {"type": "string"}},
                            "required": ["factor", "value"],
                        },
                    },
                    "machine_status": {"type": "string"},
                    "fix_options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "recommended": {"type": "boolean"},
                                "detail": {"type": "string"},
                                "commands": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "detail"],
                        },
                    },
                },
                "required": ["summary", "severity"],
            },
        },
    },
]


@dataclass
class FixOption:
    title: str
    recommended: bool
    detail: str
    commands: list


@dataclass
class AgenticReport:
    summary: str
    severity: str
    evidence: list
    machine_status: str
    fix_options: list
    tokens_used: int
    findings: list = field(default_factory=list)
    truncated: bool = False


def parse_report(args: dict, *, tokens_used: int, findings: list, truncated: bool) -> AgenticReport:
    fix_options = [
        FixOption(
            title=o.get("title", ""),
            recommended=bool(o.get("recommended", False)),
            detail=o.get("detail", ""),
            commands=o.get("commands", []) or [],
        )
        for o in (args.get("fix_options") or [])
    ]
    return AgenticReport(
        summary=args.get("summary", ""),
        severity=args.get("severity", "warning"),
        evidence=args.get("evidence") or [],
        machine_status=args.get("machine_status", ""),
        fix_options=fix_options,
        tokens_used=tokens_used,
        findings=findings,
        truncated=truncated,
    )


# transitional: telegram_bot.py still imports this until Task 5 removes it.
# Keeping it keeps the module import chain intact between tasks. Delete in Task 5.
@dataclass
class LLMAnalysis:
    root_cause: str
    severity: str
    suggested_fix: str
    fix_commands: list
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

    # ponytail: body filled in Task 3 (agentic tool-call loop). Placeholder keeps module importable.


_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
