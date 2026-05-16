from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sdk.config import get_sdk_settings


class SDKBase(DeclarativeBase):
    pass


def create_sdk_engine(database_url: str | None = None):
    url = database_url or get_sdk_settings().database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


sdk_engine = create_sdk_engine()
SDKSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sdk_engine)
_sdk_database_initialized = False


def init_sdk_database() -> None:
    global _sdk_database_initialized
    if _sdk_database_initialized:
        return
    import sdk.models  # noqa: F401

    SDKBase.metadata.create_all(bind=sdk_engine)
    _sdk_database_initialized = True


def get_sdk_db() -> Generator[Session, None, None]:
    init_sdk_database()
    db = SDKSessionLocal()
    try:
        yield db
    finally:
        db.close()
