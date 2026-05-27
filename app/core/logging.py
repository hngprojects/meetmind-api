"""Logging configuration for the application."""

import logging
import logging.config

from app.core.config import settings
from opentelemetry import trace


class OTelFormatter(logging.Formatter):
    """Injects trace_id and span_id into log records if available."""

    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            ctx = span.get_span_context()
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return super().format(record)


def setup_logging() -> None:
    """Configure root logger and suppress noisy third-party loggers.

    Uses a single console handler writing to stdout. Log level is driven by
    the ``LOG_LEVEL`` env var (default ``INFO``). SQLAlchemy engine logs are
    capped at WARNING to avoid spamming every SQL statement in INFO mode.

    Call this once before the FastAPI app is created so uvicorn inherits the
    configuration rather than overwriting it.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "()": OTelFormatter,
                    "format": (
                        "%(asctime)s [%(levelname)-8s] [%(trace_id)s-%(span_id)s] "
                        "%(name)s: %(message)s"
                    ),
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
        }
    )
