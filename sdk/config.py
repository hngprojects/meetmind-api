from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from decouple import config


class SDKSettings:
    """Environment-backed settings for the SDK product.

    These values are intentionally separate from the existing app's DB_* values
    so the SDK can run standalone or share a database by explicit configuration.
    """

    def __init__(self) -> None:
        self.public_base_url: str = config("SDK_PUBLIC_BASE_URL", default="")

        self.zoom_client_id: str = config("ZOOM_CLIENT_ID", default="")
        self.zoom_client_secret: str = config("ZOOM_CLIENT_SECRET", default="")
        self.zoom_oauth_redirect_url: str = config(
            "ZOOM_OAUTH_REDIRECT_URL", default=""
        )
        self.zoom_rtms_webhook_url: str = config("ZOOM_RTMS_WEBHOOK_URL", default="")
        self.zoom_webhook_secret_token: str = config(
            "ZOOM_WEBHOOK_SECRET_TOKEN", default=""
        )
        self.zoom_default_wake_words_raw: str = config(
            "ZOOM_DEFAULT_WAKE_WORDS", default="MeetMind,Hey MeetMind"
        )
        self.zoom_rtms_enable_audio: bool = config(
            "ZOOM_RTMS_ENABLE_AUDIO", default=True, cast=bool
        )
        self.zoom_rtms_enable_transcript: bool = config(
            "ZOOM_RTMS_ENABLE_TRANSCRIPT", default=True, cast=bool
        )

        self.sdk_database_url: str = config("SDK_DATABASE_URL", default="")
        self.sdk_db_type: str = config("SDK_DB_TYPE", default="sqlite")
        self.sdk_db_name: str = config("SDK_DB_NAME", default="sdk")
        self.sdk_db_user: str = config("SDK_DB_USER", default="")
        self.sdk_db_password: str = config("SDK_DB_PASSWORD", default="")
        self.sdk_db_host: str = config("SDK_DB_HOST", default="localhost")
        self.sdk_db_port_raw: str = config("SDK_DB_PORT", default="")
        self.sdk_sqlite_path: str = config("SDK_SQLITE_PATH", default=".sdk/sdk.sqlite")

    @property
    def zoom_default_wake_words(self) -> list[str]:
        return parse_csv(self.zoom_default_wake_words_raw)

    def database_url(self) -> str:
        if self.sdk_database_url:
            return self.sdk_database_url

        db_type = self.sdk_db_type.lower()
        if db_type == "sqlite":
            sqlite_path = Path(self.sdk_sqlite_path)
            sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{sqlite_path.as_posix()}"

        if db_type in {"postgres", "postgresql"}:
            port = int(self.sdk_db_port_raw) if self.sdk_db_port_raw else 5432
            user = quote_plus(self.sdk_db_user)
            password = quote_plus(self.sdk_db_password)
            return (
                f"postgresql://{user}:{password}@{self.sdk_db_host}:"
                f"{port}/{self.sdk_db_name}"
            )

        if db_type == "mysql":
            port = int(self.sdk_db_port_raw) if self.sdk_db_port_raw else 3306
            user = quote_plus(self.sdk_db_user)
            password = quote_plus(self.sdk_db_password)
            return (
                f"mysql+pymysql://{user}:{password}@{self.sdk_db_host}:"
                f"{port}/{self.sdk_db_name}"
            )

        raise ValueError(f"Unsupported SDK_DB_TYPE: {self.sdk_db_type}")


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_sdk_settings() -> SDKSettings:
    return SDKSettings()
