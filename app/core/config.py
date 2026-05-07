"""Application settings loaded from the environment."""

from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration backed by environment variables.

    Values are loaded from process environment and the ``.env`` file (when
    present). Field names map 1:1 to environment variables.

    Attributes:
        PROJECT_NAME: Human-readable service name surfaced in OpenAPI.
        API_V1_PREFIX: URL prefix all v1 routes are mounted under.
        DATABASE_URL: Async Postgres DSN used by the application.
        TEST_DATABASE_URL: DSN used when running the test suite.
        JWT_SECRET: Symmetric secret used to sign JWTs.
        JWT_ALGORITHM: Signing algorithm passed to ``python-jose``.
        ACCESS_TOKEN_EXPIRE_MINUTES: Lifetime of issued access tokens.
        REFRESH_TOKEN_EXPIRE_MINUTES: Lifetime of issued refresh tokens.
    """

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
    """Return the cached :class:`Settings` singleton.

    Returns:
        A populated :class:`Settings` instance. The same object is returned
        on every call thanks to ``functools.lru_cache``.
    """
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
