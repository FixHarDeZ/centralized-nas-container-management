import os

from app.notify import Notifier, TgCreds

_notifier = Notifier(
    telegram=TgCreds(
        os.environ.get("LOG_MEDIC_TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("LOG_MEDIC_TELEGRAM_CHAT_ID", ""),
    ),
    timeout=10,
)


def notify(text: str) -> list[str]:
    return _notifier.send(text)
