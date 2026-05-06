from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.responses import APIError, error, success

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(APIError)
async def handle_api_error(_: Request, exc: APIError):
    return error(
        exc.message,
        status_code=exc.status_code,
        code=exc.code,
        details=exc.details,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException):
    return error(
        exc.detail if isinstance(exc.detail, str) else "HTTP error",
        status_code=exc.status_code,
        code="http_error",
        details=exc.detail if not isinstance(exc.detail, str) else None,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    return error(
        "Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        details=exc.errors(),
    )


@app.get("/")
def root():
    return success(
        {"service": settings.PROJECT_NAME, "version": "v1"},
        message=f"{settings.PROJECT_NAME} is running",
    )
