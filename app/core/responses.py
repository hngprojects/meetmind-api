"""Standard API response envelope used by every endpoint in the codebase.

All success responses look like:
    {"success": true, "message": "...", "data": <payload>, "meta": {...}}

All error responses look like:
    {"success": false, "message": "...", "error": {"code": "...", "details": ...}}

Endpoints should return `success(...)` / `paginated(...)` and raise `APIError`
for failures (handled centrally by the exception handlers in app.main).
"""

from __future__ import annotations

import math
from typing import Any, Generic, TypeVar

from fastapi import status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

T = TypeVar("T")


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class ResponseMeta(BaseModel):
    pagination: PageMeta | None = None


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "OK"
    data: T | None = None
    meta: ResponseMeta | None = None


class APIErrorBody(BaseModel):
    code: str = Field(default="error")
    details: Any | None = None


class APIErrorResponse(BaseModel):
    success: bool = False
    message: str
    error: APIErrorBody


class APIError(Exception):
    """Domain exception that renders as a standardized error response.

    Raise this from any service or route to short-circuit a request with a
    consistent error envelope. The registered handler in ``app.main`` converts
    the exception into a :func:`error` response.

    Attributes:
        message: Human-readable error description shown to the client.
        status_code: HTTP status code returned to the client.
        code: Machine-readable error code (e.g. ``"workspace_not_found"``).
        details: Optional structured payload (field errors, debug info, ...).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "error",
        details: Any | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description.
            status_code: HTTP status code to return. Defaults to ``400``.
            code: Machine-readable error code. Defaults to ``"error"``.
            details: Optional structured payload attached to the response.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


def success(
    data: Any = None,
    *,
    message: str = "OK",
    status_code: int = status.HTTP_200_OK,
    meta: ResponseMeta | dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a standardized success response.

    Args:
        data: Payload to place under the ``data`` key. May be any
            JSON-serializable value, a Pydantic model, or ``None``.
        message: Human-readable status message. Defaults to ``"OK"``.
        status_code: HTTP status code. Defaults to ``200``.
        meta: Optional metadata (e.g. pagination). Accepts a
            :class:`ResponseMeta` or a plain dict.

    Returns:
        A :class:`fastapi.responses.JSONResponse` with the standard success
        envelope.
    """
    payload: dict[str, Any] = {"success": True, "message": message, "data": data}
    if meta is not None:
        payload["meta"] = meta if isinstance(meta, dict) else meta.model_dump()
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


def paginated(
    items: list[Any],
    *,
    page: int,
    page_size: int,
    total: int,
    message: str = "OK",
) -> JSONResponse:
    """Build a standardized success response for a paginated collection.

    Args:
        items: Page of items to return under ``data``.
        page: 1-based index of the current page.
        page_size: Maximum number of items per page.
        total: Total number of items across all pages.
        message: Human-readable status message. Defaults to ``"OK"``.

    Returns:
        A :class:`fastapi.responses.JSONResponse` with the items under
        ``data`` and a ``meta.pagination`` block describing the page.
    """
    total_pages = math.ceil(total / page_size) if page_size else 0
    meta = ResponseMeta(
        pagination=PageMeta(
            page=page, page_size=page_size, total=total, total_pages=total_pages
        )
    )
    return success(items, message=message, meta=meta)


def error(
    message: str,
    *,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    code: str = "error",
    details: Any | None = None,
) -> JSONResponse:
    """Build a standardized error response.

    Prefer raising :class:`APIError` from inside route/service code; this
    helper exists for the central exception handlers and edge cases where
    raising is awkward.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code to return. Defaults to ``400``.
        code: Machine-readable error code. Defaults to ``"error"``.
        details: Optional structured payload (field errors, debug info, ...).

    Returns:
        A :class:`fastapi.responses.JSONResponse` with the standard error
        envelope.
    """
    payload = APIErrorResponse(
        success=False,
        message=message,
        error=APIErrorBody(code=code, details=details),
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))
