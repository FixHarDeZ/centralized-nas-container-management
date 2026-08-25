"""Uploads a finished Clip to YouTube.

Deliberately no google-api-python-client: refreshing a token is one POST and a
resumable upload is two requests, and httpx is already here.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"

MAX_TITLE = 100
MAX_DESCRIPTION = 5000


class UploadError(RuntimeError):
    """The upload did not happen; the Clip is still on disk."""


def configured() -> bool:
    return all(
        os.environ.get(name)
        for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    )


async def _access_token(client: httpx.AsyncClient) -> str:
    reply = await client.post(
        TOKEN_URL,
        data={
            "client_id": os.environ["YOUTUBE_CLIENT_ID"],
            "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
    )
    if reply.status_code != 200:
        # `invalid_grant` here almost always means the consent screen is still
        # in Testing, where refresh tokens expire after 7 days.
        raise UploadError(f"ขอ access token ไม่ผ่าน ({reply.status_code}): {reply.text[:300]}")
    return reply.json()["access_token"]


def metadata(script: dict) -> dict:
    tags = [tag.lstrip("#") for tag in script.get("hashtags", [])]
    description = script.get("description", "")
    if tags:
        description = f"{description}\n\n{' '.join('#' + t for t in tags)}"
    return {
        "snippet": {
            "title": script["title"][:MAX_TITLE],
            "description": description[:MAX_DESCRIPTION],
            "tags": tags,
            "categoryId": os.environ.get("YOUTUBE_CATEGORY_ID", "28"),
        },
        "status": {
            "privacyStatus": os.environ.get("YOUTUBE_PRIVACY", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }


async def upload(clip: Path, script: dict) -> tuple[str, str]:
    """Upload the Clip. Returns (video_id, the privacy status YouTube applied).

    The status is read back rather than assumed: a project that has not passed
    Google's API compliance audit has its uploads forced to `private`, and the
    only honest way to know is to look at what came back.
    """
    if not configured():
        raise UploadError("ยังไม่ได้ตั้งค่า YouTube (รัน scripts/youtube_auth.py ก่อน)")

    size = clip.stat().st_size
    async with httpx.AsyncClient(timeout=600) as client:
        token = await _access_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        start = await client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                **headers,
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/mp4",
            },
            content=json.dumps(metadata(script)),
        )
        if start.status_code not in (200, 201):
            raise UploadError(f"เริ่มอัปโหลดไม่ได้ ({start.status_code}): {start.text[:300]}")

        session_url = start.headers.get("location")
        if not session_url:
            raise UploadError("YouTube ไม่ได้ส่ง upload session กลับมา")

        done = await client.put(
            session_url,
            headers={**headers, "Content-Type": "video/mp4", "Content-Length": str(size)},
            content=clip.read_bytes(),
        )
        if done.status_code not in (200, 201):
            raise UploadError(f"อัปโหลดล้มเหลว ({done.status_code}): {done.text[:300]}")

        body = done.json()
        privacy = body.get("status", {}).get("privacyStatus", "unknown")
        logger.info("อัปโหลดแล้ว: %s (%s)", body.get("id"), privacy)
        return body["id"], privacy
