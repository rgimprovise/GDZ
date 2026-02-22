"""
Application configuration using pydantic-settings.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Core
    env: str = "local"
    base_url: str = "http://localhost:8000"
    
    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tutorbot"
    postgres_user: str = "tutorbot"
    postgres_password: str = "tutorbot"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Data directory (PDFs, OCR output) — для загрузки учебников и пути к файлам
    data_dir: str = "data"
    
    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "tutorbot"
    
    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_tma_bot_username: str = ""
    
    # OpenAI
    openai_api_key: str = ""
    openai_model_text: str = "gpt-4o"
    openai_model_vision: str = "gpt-4o"
    
    # Security
    jwt_secret: str = "change_me_in_production"
    
    @property
    def database_url(self) -> str:
        """Construct database URL from components."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def async_database_url(self) -> str:
        """Construct async database URL for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
