"""Logging configuration for the application."""

import logging
import logging.config

from app.core.config import settings


def setup_logging() -> None:
    """Configure root logger and suppress noisy third-party loggers.

    Uses a single console handler writing to stdout. Log level is driven by
    the ``LOG_LEVEL`` env var (default ``INFO``). SQLAlchemy engine logs are
    capped at WARNING to avoid spamming every SQL statement in INFO mode.

    Call this once before the FastAPI app is created so uvicorn inherits the
    configuration rather than overwriting it.
    """
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": settings.LOG_LEVEL.upper(),
            "handlers": ["console"],
        },
        "loggers": {
            # Let uvicorn logs flow through the root handler/formatter
            "uvicorn": {"propagate": True, "handlers": []},
            "uvicorn.access": {"propagate": True, "handlers": []},
            "uvicorn.error": {"propagate": True, "handlers": []},
            # Silence per-statement SQL logs unless explicitly requested
            "sqlalchemy.engine": {
                "level": "WARNING",
                "propagate": True,
                "handlers": [],
            },
        },
    })
