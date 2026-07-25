import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.commands import _handle_callback


@pytest.mark.asyncio
async def test_pr_callback_opens_pr_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    import app.config
    app.config._config = None

    report = {"fix_options": [{"title": "bump", "recommended": True, "detail": "d",
                               "commands": [], "file_changes": [{"path": "x.yml", "find": "a", "replace": "b"}]}]}
    db = AsyncMock()
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value=(json.dumps(report),))
    db.execute = AsyncMock(return_value=cur)
    db.commit = AsyncMock()
    tg = MagicMock()
    tg.answer_callback = AsyncMock()
    tg.send_message = AsyncMock()

    with (
        patch("app.commands.get_db", AsyncMock(return_value=db)),
        patch("app.commands.get_telegram_bot", return_value=tg),
        patch("app.commands.create_fix_pr", new_callable=AsyncMock, return_value=(True, "https://gh/pr/1")) as mock_pr,
    ):
        await _handle_callback({"id": "cb1", "data": "pr:5:0"})

    mock_pr.assert_awaited_once()
    args = mock_pr.await_args
    assert args.kwargs.get("incident_id", args.args[0] if args.args else None) == 5 or args.args[0] == 5
    # a Telegram reply with the URL was sent
    assert any("https://gh/pr/1" in str(c.args) for c in tg.send_message.await_args_list)
    # an actions row was written
    assert any("INSERT INTO actions" in str(c.args[0]) for c in db.execute.await_args_list)
    app.config._config = None
