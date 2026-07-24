from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.main import app


@pytest.mark.asyncio
async def test_webhook_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.webhook.handle_incident", new_callable=AsyncMock, return_value=1) as mock_handle:
            resp = await client.post("/webhook/uptime-kuma", json={
                "heartbeat": {
                    "status": 0,
                    "time": "2026-07-23 07:40:00",
                    "msg": "connect ECONNREFUSED",
                },
                "monitor": {
                    "name": "Outline Wiki",
                    "url": "http://192.168.1.111:3000",
                    "hostname": "192.168.1.111",
                    "port": "3000",
                },
            })

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "accepted"
            mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_rejects_invalid():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhook/uptime-kuma", json={"invalid": "data"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"


@pytest.mark.asyncio
async def test_webhook_test_notification():
    """Uptime Kuma test notification sends null heartbeat/monitor."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/webhook/uptime-kuma", json={
            "heartbeat": None,
            "monitor": None,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "test_ok"


@pytest.mark.asyncio
async def test_webhook_null_hostname_port():
    """Uptime Kuma Docker Container monitor sends null hostname/port."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.webhook.handle_incident", new_callable=AsyncMock, return_value=1) as mock_handle:
            resp = await client.post("/webhook/uptime-kuma", json={
                "heartbeat": {
                    "status": 0,
                    "time": "2026-07-24 04:10:05",
                    "msg": "timeout of 48000ms exceeded",
                },
                "monitor": {
                    "name": "News Feed",
                    "url": "https://",
                    "hostname": None,
                    "port": None,
                    "type": "docker",
                },
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "accepted"
            mock_handle.assert_called_once()
