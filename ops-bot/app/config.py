from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    mimo_api_key: str = ""
    mimo_base_url: str = "https://token-plan-sgp.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.5-pro"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # SSH (key-only, no password)
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_key_path: str = "/app/data/ssh/id_ed25519"
    ssh_port: int = 22

    # Watchtower
    watchtower_grace_minutes: int = 5

    # Webhook security
    kuma_webhook_secret: str = ""

    # Debounce
    debounce_minutes: int = 15

    # Dashboard
    dashboard_basic_auth_user: str = "admin"
    dashboard_basic_auth_password: str = ""

    # DB
    db_path: str = "/app/data/ops_bot.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


_config: Optional[Settings] = None


def get_config() -> Settings:
    global _config
    if _config is None:
        _config = Settings()
    return _config
