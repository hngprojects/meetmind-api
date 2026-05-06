from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "fastapi-starter"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: PostgresDsn
    TEST_DATABASE_URL: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_MINUTES: int


@lru_cache
def get_settings() -> Settings:
    """Return an application Settings singleton loaded from the environment."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
