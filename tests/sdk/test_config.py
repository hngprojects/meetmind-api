from sdk.config import SDKSettings


def clear_sdk_env(monkeypatch):
    keys = [
        "SDK_DATABASE_URL",
        "SDK_DB_TYPE",
        "SDK_DB_NAME",
        "SDK_DB_USER",
        "SDK_DB_PASSWORD",
        "SDK_DB_HOST",
        "SDK_DB_PORT",
        "SDK_SQLITE_PATH",
    ]
    for key in keys:
        monkeypatch.setenv(key, "")


def test_database_url_prefers_explicit_override(monkeypatch):
    clear_sdk_env(monkeypatch)
    monkeypatch.setenv("SDK_DATABASE_URL", "postgresql://user:pass@db:5432/sdk")

    assert SDKSettings().database_url() == "postgresql://user:pass@db:5432/sdk"


def test_database_url_normalizes_asyncpg_override_for_sync_sdk(monkeypatch):
    clear_sdk_env(monkeypatch)
    monkeypatch.setenv(
        "SDK_DATABASE_URL",
        "postgresql+asyncpg://user:pass@db:5432/sdk",
    )

    assert SDKSettings().database_url() == "postgresql+psycopg2://user:pass@db:5432/sdk"


def test_database_url_empty_db_type_falls_back_to_sqlite(monkeypatch, tmp_path):
    clear_sdk_env(monkeypatch)
    sqlite_path = tmp_path / "sdk.sqlite"
    monkeypatch.setenv("SDK_DB_TYPE", "")
    monkeypatch.setenv("SDK_SQLITE_PATH", str(sqlite_path))

    assert SDKSettings().database_url() == f"sqlite:///{sqlite_path.as_posix()}"


def test_database_url_uses_sqlite_path_for_local(monkeypatch, tmp_path):
    clear_sdk_env(monkeypatch)
    sqlite_path = tmp_path / "meetmind.sqlite"
    monkeypatch.setenv("SDK_DB_TYPE", "sqlite")
    monkeypatch.setenv("SDK_SQLITE_PATH", str(sqlite_path))

    assert SDKSettings().database_url() == f"sqlite:///{sqlite_path.as_posix()}"


def test_database_url_builds_postgres_from_discrete_env(monkeypatch):
    clear_sdk_env(monkeypatch)
    monkeypatch.setenv("SDK_DB_TYPE", "postgresql")
    monkeypatch.setenv("SDK_DB_USER", "sdk_user")
    monkeypatch.setenv("SDK_DB_PASSWORD", "sdk_pass")
    monkeypatch.setenv("SDK_DB_HOST", "postgres.internal")
    monkeypatch.setenv("SDK_DB_PORT", "5433")
    monkeypatch.setenv("SDK_DB_NAME", "sdk_db")

    assert (
        SDKSettings().database_url()
        == "postgresql://sdk_user:sdk_pass@postgres.internal:5433/sdk_db"
    )


def test_database_url_uses_db_specific_default_ports(monkeypatch):
    clear_sdk_env(monkeypatch)
    monkeypatch.setenv("SDK_DB_TYPE", "mysql")
    monkeypatch.setenv("SDK_DB_USER", "sdk_user")
    monkeypatch.setenv("SDK_DB_PASSWORD", "sdk_pass")
    monkeypatch.setenv("SDK_DB_HOST", "mysql.internal")
    monkeypatch.setenv("SDK_DB_NAME", "sdk_db")

    assert (
        SDKSettings().database_url()
        == "mysql+pymysql://sdk_user:sdk_pass@mysql.internal:3306/sdk_db"
    )


def test_default_wake_words_are_configurable(monkeypatch):
    monkeypatch.setenv("ZOOM_DEFAULT_WAKE_WORDS", "Atlas,Hey Atlas")

    assert SDKSettings().zoom_default_wake_words == ["Atlas", "Hey Atlas"]
