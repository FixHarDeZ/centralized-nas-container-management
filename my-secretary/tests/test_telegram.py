import pytest
from unittest.mock import AsyncMock, patch
import telegram_client


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
