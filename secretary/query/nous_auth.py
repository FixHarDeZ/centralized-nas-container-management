import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_DEVICE_CODE_URL = "https://portal.nousresearch.com/api/oauth/device/code"
_TOKEN_URL = "https://portal.nousresearch.com/api/oauth/token"
_CLIENT_ID = "hermes-cli"
_REFRESH_BUFFER_SECS = 60


def _token_file() -> Path:
    return Path(os.getenv("NOUS_TOKEN_FILE", "/data/nous_token.json"))


_TERMINAL_OAUTH_ERRORS = {"access_denied", "expired_token", "invalid_client", "invalid_grant"}


class NousTokenManager:
    def __init__(self):
        self._tokens: dict | None = None
        self._poll_task: asyncio.Task | None = None
        self._refresh_lock = asyncio.Lock()
        self._load()

    def _load(self):
        path = _token_file()
        if path.exists():
            try:
                self._tokens = json.loads(path.read_text())
            except Exception:
                self._tokens = None

    def _save(self, tokens: dict):
        self._tokens = tokens
        path = _token_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens))
        tmp.replace(path)

    def _is_valid(self) -> bool:
        return bool(
            self._tokens
            and self._tokens.get("expires_at", 0) > time.time() + _REFRESH_BUFFER_SECS
        )

    async def start_device_flow(self) -> dict:
        if self._is_valid():
            return {"authenticated": True, "message": "Already authenticated"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _DEVICE_CODE_URL,
                json={"client_id": _CLIENT_ID, "scope": "inference:invoke"},
            )
            resp.raise_for_status()
            data = resp.json()

        device_code = data["device_code"]
        interval = int(data.get("interval", 5))
        expires_in = int(data["expires_in"])

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = asyncio.create_task(
            self._poll_for_token(device_code, interval, expires_in)
        )

        return {
            "authenticated": False,
            "verification_uri": data["verification_uri"],
            "user_code": data["user_code"],
            "expires_in": expires_in,
            "message": f"Open {data['verification_uri']} and enter code: {data['user_code']}",
        }

    async def _poll_for_token(self, device_code: str, interval: int, expires_in: int):
        deadline = time.time() + expires_in
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                await asyncio.sleep(interval)
                try:
                    resp = await client.post(
                        _TOKEN_URL,
                        json={
                            "client_id": _CLIENT_ID,
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                    if resp.status_code == 200:
                        d = resp.json()
                        self._save({
                            "access_token": d["access_token"],
                            "refresh_token": d["refresh_token"],
                            "expires_at": int(time.time()) + int(d["expires_in"]),
                        })
                        return
                    error = (resp.json() if resp.content else {}).get("error", "")
                    if error in _TERMINAL_OAUTH_ERRORS:
                        log.warning("Nous token poll: terminal error %r — aborting", error)
                        return
                    if error != "authorization_pending":
                        log.warning("Nous token poll: unexpected status %s / %r, retrying", resp.status_code, error)
                except Exception as exc:
                    log.warning("Nous token poll: network error (%s), retrying", exc)

    async def get_access_token(self) -> str:
        if not self._tokens:
            raise RuntimeError("Nous not authenticated — call GET /nous/auth first")
        if not self._is_valid():
            async with self._refresh_lock:
                if not self._is_valid():
                    await self._refresh()
        return self._tokens["access_token"]

    async def _refresh(self):
        if not self._tokens or not self._tokens.get("refresh_token"):
            raise RuntimeError("Nous not authenticated — call GET /nous/auth first")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _TOKEN_URL,
                json={
                    "client_id": _CLIENT_ID,
                    "refresh_token": self._tokens["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            d = resp.json()
        self._save({
            "access_token": d["access_token"],
            "refresh_token": d.get("refresh_token", self._tokens["refresh_token"]),
            "expires_at": int(time.time()) + int(d["expires_in"]),
        })

    def auth_status(self) -> dict:
        if not self._tokens:
            return {"authenticated": False, "expires_at": None}
        expires_at = self._tokens.get("expires_at")
        authenticated = bool(expires_at and expires_at > time.time())
        return {"authenticated": authenticated, "expires_at": expires_at}


token_manager = NousTokenManager()
