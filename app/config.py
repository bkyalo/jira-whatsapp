from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    jira_webhook_secret: str
    openwa_base_url: str = "https://whatsapp.werevu.co.ke"
    openwa_api_key: str
    openwa_session_id: str
    user_map_path: str = "config/user_map.json"
    host: str = "127.0.0.1"
    port: int = 6060
    log_level: str = "INFO"
    openwa_max_retries: int = 2
    openwa_retry_delay_seconds: float = 1.0
    # Optional — required to download Jira attachment URLs (Atlassian-hosted images)
    jira_email: str = ""
    jira_api_token: str = ""

    @property
    def user_map_file(self) -> Path:
        return Path(self.user_map_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
