from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LINE_SECRETARY_CHANNEL_SECRET: str
    LINE_SECRETARY_CHANNEL_ACCESS_TOKEN: str
    LINE_SECRETARY_ALLOWED_USER_IDS: str  # comma-separated LINE user IDs
    NOTION_TOKEN: str

    # AI provider: "auto" (Groq primary + OpenRouter fallback), "groq", or "openrouter"
    AI_PROVIDER: str = "auto"
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    NOTION_QUICK_NOTE_PAGE_ID: str = ""

    # Telegram bot (optional — leave blank to disable)
    TELEGRAM_BOT_TOKEN: str = ""
    # Full HTTPS URL Telegram will POST updates to, e.g. https://<NAS_HOST>:5058/webhook/telegram
    TELEGRAM_WEBHOOK_URL: str = ""
    # Allowed Telegram chat IDs (comma-separated). If empty, accepts any chat.
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""

    DATA_DIR: str = "/data"

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}

    @property
    def allowed_telegram_chat_ids(self) -> set[str]:
        if not self.TELEGRAM_ALLOWED_CHAT_IDS:
            return set()
        return {cid.strip() for cid in self.TELEGRAM_ALLOWED_CHAT_IDS.split(",")}


settings = Settings()
