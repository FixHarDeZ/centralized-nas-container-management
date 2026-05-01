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

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}


settings = Settings()
