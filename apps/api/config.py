"""
Application configuration using pydantic-settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    env: str = "local"
    base_url: str = "http://localhost:8000"

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tutorbot"
    postgres_user: str = "tutorbot"
    postgres_password: str = "tutorbot"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_tma_bot_username: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_assistant_id: str = ""
    openai_model_vision: str = "gpt-4o"

    # Security
    jwt_secret: str = "change_me_in_production"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
