from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LINE_SECRETARY_CHANNEL_SECRET: str
    LINE_SECRETARY_CHANNEL_ACCESS_TOKEN: str
    LINE_SECRETARY_ALLOWED_USER_IDS: str  # comma-separated LINE user IDs
    GROQ_API_KEY: str
    NOTION_TOKEN: str

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}


settings = Settings()
