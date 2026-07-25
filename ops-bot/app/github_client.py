# ops-bot/app/github_client.py
from __future__ import annotations

import base64
import logging
import re
import time
from typing import Tuple

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

API = "https://api.github.com"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:24] or "fix"


async def create_fix_pr(incident_id: int, title: str, file_changes: list) -> Tuple[bool, str]:
    cfg = get_config()
    if not cfg.github_token or not cfg.github_repo:
        return (False, "GitHub token/repo ยังไม่ได้ตั้งค่า")
    if not file_changes:
        return (False, "fix นี้ไม่มีการแก้ไฟล์ (advisory เท่านั้น)")

    headers = {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"{API}/repos/{cfg.github_repo}"
    branch = f"fix/incident-{incident_id}-{_slug(title)}-{int(time.time())}"

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(base)
            if r.status_code != 200:
                return (False, f"เข้าถึง repo ไม่ได้ ({r.status_code})")
            default_branch = r.json().get("default_branch", "main")

            r = await client.get(f"{base}/git/ref/heads/{default_branch}")
            if r.status_code != 200:
                return (False, f"อ่าน branch {default_branch} ไม่ได้ ({r.status_code})")
            base_sha = r.json()["object"]["sha"]

            r = await client.post(
                f"{base}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if r.status_code not in (200, 201):
                return (False, f"สร้าง branch ไม่ได้ ({r.status_code})")

            for ch in file_changes:
                path = ch.get("path", "")
                find = ch.get("find", "")
                replace = ch.get("replace", "")
                if not path:
                    return (False, "file_changes ขาด path")
                r = await client.get(f"{base}/contents/{path}", params={"ref": branch})
                if r.status_code != 200:
                    return (False, f"ไม่พบไฟล์ {path} ใน repo ({r.status_code})")
                meta = r.json()
                content = base64.b64decode(meta["content"]).decode("utf-8")
                if find not in content:
                    return (False, f"หา '{find[:40]}' ในไฟล์ {path} ไม่เจอ — แก้ manual")
                new_content = content.replace(find, replace)
                r = await client.put(
                    f"{base}/contents/{path}",
                    json={
                        "message": f"fix(incident-{incident_id}): {title} [{path}]",
                        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                        "sha": meta["sha"],
                        "branch": branch,
                    },
                )
                if r.status_code not in (200, 201):
                    return (False, f"เขียนไฟล์ {path} ไม่ได้ ({r.status_code})")

            body = (
                f"Auto-generated fix for incident #{incident_id}.\n\n{title}\n\n"
                "⚠️ Review, merge, then deploy manually (make secrets && ./scripts/deploy.sh)."
            )
            r = await client.post(
                f"{base}/pulls",
                json={"title": f"fix(incident-{incident_id}): {title}", "head": branch, "base": default_branch, "body": body},
            )
            if r.status_code not in (200, 201):
                return (False, f"เปิด PR ไม่ได้ ({r.status_code})")
            return (True, r.json()["html_url"])
    except Exception as e:
        logger.error(f"create_fix_pr failed: {e}")
        return (False, f"GitHub error: {e}")
