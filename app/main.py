"""FastAPI application entry point.

Wires the v1 router and registers the global exception handlers that map
:class:`app.core.responses.APIError`, framework HTTP errors, and validation
errors to the standardized response envelope.
"""

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.responses import APIError, error, success

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(APIError)
async def handle_api_error(_: Request, exc: APIError):
    """Render an :class:`APIError` as the standardized error envelope.

    Args:
        _: The incoming request (unused).
        exc: The raised domain error carrying ``message``, ``status_code``,
            ``code`` and optional ``details``.

    Returns:
        A :class:`fastapi.responses.JSONResponse` with the error envelope.
    """
    return error(
        exc.message,
        status_code=exc.status_code,
        code=exc.code,
        details=exc.details,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException):
    """Render any uncaught HTTP exception as the standardized envelope.

    Args:
        _: The incoming request (unused).
        exc: The Starlette/FastAPI HTTP exception.

    Returns:
        A :class:`fastapi.responses.JSONResponse` with ``code="http_error"``.
        Non-string ``detail`` payloads are forwarded under ``error.details``.
    """
    return error(
        exc.detail if isinstance(exc.detail, str) else "HTTP error",
        status_code=exc.status_code,
        code="http_error",
        details=exc.detail if not isinstance(exc.detail, str) else None,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    """Render Pydantic request validation failures using the error envelope.

    Args:
        _: The incoming request (unused).
        exc: The raised :class:`RequestValidationError`.

    Returns:
        A :class:`fastapi.responses.JSONResponse` with HTTP ``422`` and the
        per-field errors under ``error.details``.
    """
    return error(
        "Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        details=jsonable_encoder(exc.errors()),
    )


@app.get("/")
def root():
    """Root liveness endpoint used as a smoke test in tests and monitoring.

    Returns:
        A standardized success envelope identifying the running service.
    """
    return success(
        {"service": settings.PROJECT_NAME, "version": "v1"},
        message=f"{settings.PROJECT_NAME} is running",
    )
