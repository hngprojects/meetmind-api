"""Authentication & session endpoints (login, register, password reset, SSO)."""

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
    """Register a new user, issue auth tokens, and attach cookies to the response."""
    try:
        user = await AuthService.create_user(request, db)
    except UserAlreadyExistsException as e:
        raise APIError(
            str(e),
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
    """Verify a user's email address using a one-time token."""
    user, err = await verification_service.verify_email(db, payload.token)
    if err:
        raise APIError(err, code="email_verification_failed")

    return success(
        {"id": str(user.id), "email": user.email},
        message="Email verified successfully",
    )


@router.post("/resend-verification")
async def resend_verification(
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_session),
):
    """Re-issue an email verification token for an unverified account."""
    _, err = await verification_service.resend_verification(db, payload.email)
    if err:
        raise APIError(err, code="resend_verification_failed")

    return success(message="Verification email resent")
