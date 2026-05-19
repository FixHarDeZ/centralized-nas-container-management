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

    # Proactive reminders: comma-separated Notion database IDs to check for today's dates.
    # Leave empty to disable.
    NOTION_REMINDER_DB_IDS: str = ""
    # Time to send daily reminders (HH:MM, Bangkok time UTC+7)
    NOTION_REMINDER_TIME: str = "08:00"

    DATA_DIR: str = "/data"

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}


settings = Settings()
