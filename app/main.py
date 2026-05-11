"""FastAPI application entry point.

Wires the v1 router and registers the global exception handlers that map
:class:`app.core.responses.APIError`, framework HTTP errors, and validation
errors to the standardized response envelope.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import setup_logging
from app.core.middleware import JWTBlacklistMiddleware
from app.core.redis import redis_client
from app.core.responses import APIError, error, success
from app.db.session import engine

setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting %s", settings.PROJECT_NAME)
    yield
    logger.info("Shutting down %s — disposing DB engine", settings.PROJECT_NAME)
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.rstrip("/") for origin in settings.CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(JWTBlacklistMiddleware)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(RateLimitExceeded)
async def handle_rate_limit_error(_: Request, exc: RateLimitExceeded):
    return error(
        "Too many requests — please slow down.",
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        code="rate_limit_exceeded",
        details={"limit": str(exc.detail)},
    )


@app.exception_handler(APIError)
async def handle_api_error(_: Request, exc: APIError):
    """Render an :class:`APIError` as the standardized error envelope."""
    return error(
        exc.message,
        status_code=exc.status_code,
        code=exc.code,
        details=exc.details,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException):
    """Render any uncaught HTTP exception as the standardized envelope."""
    return error(
        exc.detail if isinstance(exc.detail, str) else "HTTP error",
        status_code=exc.status_code,
        code="http_error",
        details=exc.detail if not isinstance(exc.detail, str) else None,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    """Render Pydantic request validation failures using the error envelope."""
    return error(
        "Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        details=jsonable_encoder(exc.errors()),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception):
    """Catch-all for any unhandled exception — never expose internals."""
    logger.exception("Unhandled exception: %s", exc)
    return error(
        "An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
    )


@app.get("/")
def root():
    """Root liveness endpoint."""
    return success(
        {"service": settings.PROJECT_NAME, "version": "v1"},
        message=f"{settings.PROJECT_NAME} is running",
    )
