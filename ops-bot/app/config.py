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

    # Router SSH for Mesh Node auto-heal (key-only, host key pinned,
    # separate from the NAS client above)
    router_ssh_host: str = ""
    router_ssh_user: str = ""
    router_ssh_port: int = 22
    router_ssh_key_path: str = "/app/data/ssh/router_ed25519"
    router_ssh_host_key_sha256: str = ""

    # Mesh Node auto-heal — off unless mesh_node_host and router_ssh_host are set
    mesh_node_host: str = ""
    mesh_node_probe_port: int = 80
    mesh_monitor_name: str = "Mesh Node"
    mesh_group_name: str = "Home Network Monitor"
    mesh_down_minutes: float = 5
    mesh_verify_minutes: float = 5
    mesh_quiet_minutes: float = 3
    mesh_cooldown_minutes: float = 30
    mesh_daily_cap: int = 3
    mesh_max_failures: int = 2
    mesh_state_file: str = "/app/data/mesh_heal.json"

    # Watchtower
    watchtower_grace_minutes: int = 5

    # Deploy window marker written by scripts/deploy.sh (epoch seconds)
    maintenance_file: str = "/app/maintenance/until"

    # Webhook security
    kuma_webhook_secret: str = ""

    # GitHub (fix-as-PR)
    github_token: str = ""
    github_repo: str = ""  # owner/repo

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
