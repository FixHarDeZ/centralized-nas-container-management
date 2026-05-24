import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import telegram_client
from config import Settings


@pytest.mark.asyncio
async def test_send_message_short():
    with patch("telegram_client.httpx.AsyncClient") as MockClient:
        mock_post = AsyncMock()
        MockClient.return_value.__aenter__.return_value.post = mock_post
        await telegram_client.send_message(12345, "hello", "TOKEN")
        mock_post.assert_called_once_with(
            "https://api.telegram.org/botTOKEN/sendMessage",
            json={"chat_id": 12345, "text": "hello"},
            timeout=10,
        )


@pytest.mark.asyncio
async def test_send_message_splits_at_4096():
    long_text = "x" * 5000
    with patch("telegram_client.httpx.AsyncClient") as MockClient:
        mock_post = AsyncMock()
        MockClient.return_value.__aenter__.return_value.post = mock_post
        await telegram_client.send_message(12345, long_text, "TOKEN")
        assert mock_post.call_count == 2
        first_call_text = mock_post.call_args_list[0].kwargs["json"]["text"]
        second_call_text = mock_post.call_args_list[1].kwargs["json"]["text"]
        assert len(first_call_text) == 4096
        assert len(second_call_text) == 904
        assert first_call_text + second_call_text == long_text


@pytest.mark.asyncio
async def test_register_webhook():
    with patch("telegram_client.httpx.AsyncClient") as MockClient:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = AsyncMock()
        mock_post = AsyncMock(return_value=mock_resp)
        MockClient.return_value.__aenter__.return_value.post = mock_post
        await telegram_client.register_webhook("TOKEN", "https://nas:8443/webhook/telegram", "SECRET")
        mock_post.assert_called_once_with(
            "https://api.telegram.org/botTOKEN/setWebhook",
            json={
                "url": "https://nas:8443/webhook/telegram",
                "secret_token": "SECRET",
                "allowed_updates": ["message"],
            },
            timeout=15,
        )
        mock_resp.raise_for_status.assert_called_once()


def test_telegram_allowed_chat_ids_parsed():
    s = Settings(
        LINE_SECRETARY_CHANNEL_SECRET="s",
        LINE_SECRETARY_CHANNEL_ACCESS_TOKEN="t",
        LINE_SECRETARY_ALLOWED_USER_IDS="U1",
        NOTION_TOKEN="n",
        TELEGRAM_ALLOWED_CHAT_IDS="111,222, 333",
    )
    assert s.telegram_allowed_chat_ids == {"111", "222", "333"}


def test_telegram_allowed_chat_ids_empty():
    s = Settings(
        LINE_SECRETARY_CHANNEL_SECRET="s",
        LINE_SECRETARY_CHANNEL_ACCESS_TOKEN="t",
        LINE_SECRETARY_ALLOWED_USER_IDS="U1",
        NOTION_TOKEN="n",
        TELEGRAM_ALLOWED_CHAT_IDS="",  # explicitly empty, ignores env
    )
    assert s.telegram_allowed_chat_ids == set()


# ── Telegram webhook endpoint tests ───────────────────────────────────────────

import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def _tg_payload(chat_id: int, text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def test_telegram_webhook_wrong_secret(client):
    resp = client.post(
        "/webhook/telegram",
        json=_tg_payload(9999, "hello"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"},
    )
    assert resp.status_code == 403


def test_telegram_webhook_missing_secret(client):
    resp = client.post("/webhook/telegram", json=_tg_payload(9999, "hello"))
    assert resp.status_code == 403


def test_telegram_webhook_no_message(client):
    resp = client.post(
        "/webhook/telegram",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_telegram_webhook_no_text(client):
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 9999, "type": "private"},
            "sticker": {"file_id": "abc"},
        },
    }
    resp = client.post(
        "/webhook/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_telegram_webhook_unauthorized_chat(client):
    resp = client.post(
        "/webhook/telegram",
        json=_tg_payload(8888, "hello"),  # 8888 not in allowed list (only 9999)
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_telegram_webhook_dispatches_handle_message(client):
    with patch("main.handle_message", new_callable=AsyncMock) as mock_handle:
        resp = client.post(
            "/webhook/telegram",
            json=_tg_payload(9999, "สวัสดีค่ะ"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_handle.assert_called_once()
    call_args = mock_handle.call_args
    assert call_args.args[0] == "tg_9999"
    assert call_args.args[1] == "สวัสดีค่ะ"
