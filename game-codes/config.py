from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    telegram_token: str = Field(
        default="", alias="GAME_CODES_TELEGRAM_BOT_TOKEN",
        description="Telegram bot token for game-codes notifications",
    )
    telegram_chat_id: str = Field(
        default="", alias="TELEGRAM_CHAT_ID",
        description="Telegram chat ID for game-codes notifications",
    )
    state_file: Path = Field(
        default=Path("seen_codes.json"), alias="STATE_FILE",
        description="Path to the seen-codes JSON state file",
    )
    poll_interval: int = Field(
        default=0, alias="POLL_INTERVAL", ge=0,
        description="Loop interval in seconds; 0 = run once",
    )


settings = Settings()

TELEGRAM_TOKEN = settings.telegram_token.strip()
TELEGRAM_CHAT_ID = settings.telegram_chat_id.strip()
STATE_FILE = settings.state_file
POLL_INTERVAL = settings.poll_interval
