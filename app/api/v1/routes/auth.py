"""Authentication & session endpoints (signup, email verification, etc.)."""

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UserAlreadyExistsException
from app.core.responses import APIError, success
from app.db.session import get_session
from app.schemas.auth import SignupRequest
from app.schemas.verification import ResendVerificationRequest, VerifyEmailRequest
from app.services.auth import AuthService
from app.services.verification_service import VerificationService

router = APIRouter()
logger = logging.getLogger(__name__)
verification_service = VerificationService()


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    """Register a new user, issue auth tokens, and attach session cookies.

    Args:
        request: Validated signup payload (name, email, password).
        response: FastAPI response object used to set auth cookies.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope containing the new user identifiers
        and freshly issued ``access_token`` / ``refresh_token`` strings.

    Raises:
        APIError: ``user_already_exists`` if the email is already registered,
            or ``internal_error`` for any unexpected failure.
    """
    try:
        user = await AuthService.create_user(request, db)
    except UserAlreadyExistsException as exc:
        raise APIError(
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
            code="user_already_exists",
        )
    except Exception:
        logger.exception("Unexpected error during signup")
        raise APIError(
            "Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
        )

    access_token = await AuthService.create_access_token(user)
    refresh_token = await AuthService.create_refresh_token(db, user.id)

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
        samesite="lax",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
        samesite="lax",
    )

    return success(
        {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
        message="Account created successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_session),
):
    """Verify a user's email address using a single-use token.

    Args:
        payload: Body containing the raw verification ``token``.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope with the verified user's ``id``
        and ``email``.
    """
    user = await verification_service.verify_email(db, payload.token)
    return success(
        {"id": str(user.id), "email": user.email},
        message="Email verified successfully",
    )


@router.post("/resend-verification")
async def resend_verification(
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_session),
):
    """Reissue a verification email for an unverified account.

    Args:
        payload: Body containing the user's ``email``.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope acknowledging the resend.
    """
    await verification_service.resend_verification(db, payload.email)
    return success(message="Verification email resent")
