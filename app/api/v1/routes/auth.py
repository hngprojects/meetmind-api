"""Authentication & session endpoints (signup, email verification, etc.)."""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UserAlreadyExistsException
from app.core.limiter import limiter
from app.core.responses import APIError, success
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SignupRequest,
)
from app.schemas.verification import ResendVerificationRequest, VerifyEmailRequest
from app.services import google_oauth
from app.services.auth import AuthService
from app.services.email_service import send_password_reset_email
from app.services.verification_service import VerificationService

router = APIRouter()
logger = logging.getLogger(__name__)
verification_service = VerificationService()


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    payload: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    background_tasks: BackgroundTasks = None,
):
    """Register a new user, issue auth tokens, and attach session cookies.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Validated signup payload (name, email, password).
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
        user = await AuthService.create_user(payload, db)
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

    try:
        await verification_service.create_verification_token(
            db, user, background_tasks=background_tasks
        )
    except Exception:
        logger.exception("Failed to complete signup for user %s", user.id)
        raise APIError(
            "Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
        )

    return success(
        {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "next_step": "verify_email",
            "onboarding_completed": user.onboarding_completed,
        },
        message="Account created successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/verify-email")
@limiter.limit("10/minute")
async def verify_email(
    request: Request,
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_session),
):
    """Verify a user's email address using a single-use token.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Body containing the raw verification ``token``.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope with the verified user's ``id``
        and ``email``.
    """
    user = await verification_service.verify_email(db, payload.token)
    return success(
        {
            "id": str(user.id),
            "email": user.email,
            "next_step": AuthService.get_next_step(user),
        },
        message="Email verified successfully",
    )


@router.post("/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_session),
    background_tasks: BackgroundTasks = None,
):
    """Reissue a verification email for an unverified account.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Body containing the user's ``email``.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope acknowledging the resend.
    """
    await verification_service.resend_verification(
        db, payload.email, background_tasks=background_tasks
    )
    return success(message="Verification email resent")


async def _process_password_reset(email: str) -> None:
    """Background task: generate and email a reset token if the address is registered.

    Runs after the 200 response is already sent, so response timing is
    identical whether or not the email exists (criteria 6 + 7). Any failure
    is logged but cannot surface as a 500 since the response is already sent.
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if not user:
                return
            raw_token = await AuthService.create_password_reset_token(db, user)
            await send_password_reset_email(user.email, user.name, raw_token)
        except Exception:
            logger.exception("Failed to process password reset for %s", email)


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_session),
    background_tasks: BackgroundTasks = None,
):
    """Validate a reset token and update the user's password.

    Token validation (exists, not expired, not already used) and the password
    write are committed together so no partial update is ever persisted.
    All token failure modes return the same generic 400 to avoid revealing
    which specific check failed.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Body containing the raw ``token`` and the new ``password``.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope with ``next_step: "login"``.

    Raises:
        APIError: 400 if the token is invalid, expired, or already used.
        APIError: 500 for any unexpected DB or network failure.
    """
    try:
        await AuthService.reset_password(
            payload.token, payload.password, db, background_tasks=background_tasks
        )
    except APIError:
        raise
    except Exception:
        logger.exception("Unexpected error during password reset")
        raise APIError(
            "Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
        )

    msg = "Password reset successfully. You can now sign in with your new password."

    return success({"next_step": "login"}, message=msg)


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
):
    """Accept a password reset request and queue delivery for registered addresses.

    Always returns 200 with an identical response regardless of whether the
    email is registered, preventing account enumeration via response body,
    status code, or timing difference.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Body containing the ``email`` to reset.
        background_tasks: FastAPI background task queue.

    Returns:
        A standardized success envelope with ``next_step: "check_email"``.
    """
    background_tasks.add_task(_process_password_reset, payload.email)
    return success(
        {"next_step": "check_email"},
        message="If that email is registered, a reset link is on its way.",
    )


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    """Authenticate with email and password, issue auth tokens.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Validated login payload (email, password).
        response: FastAPI response object used to set auth cookies.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope with the user and freshly issued tokens.

    Raises:
        APIError: ``invalid_credentials`` if the email or password is wrong.
    """
    user = await AuthService.login(payload.email, payload.password, db)

    try:
        access_token = await AuthService.create_access_token(user)
        ip = request.client.host if request.client else None
        refresh_token, refresh_expires_at = await AuthService.create_refresh_token(
            db, user.id, ip_address=ip
        )
    except Exception:
        logger.exception("Failed to issue tokens for user %s", user.id)
        raise APIError(
            "Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
        )

    expiry_minutes = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    access_expires_at = datetime.now(timezone.utc) + expiry_minutes

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
            "next_step": AuthService.get_next_step(user),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_token_expires_at": access_expires_at.isoformat(),
            "refresh_token_expires_at": refresh_expires_at.isoformat(),
        },
        message="Login successful",
    )


@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    payload: RefreshTokenRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    """Exchange a valid refresh token for a new access token.

    Args:
        request: Incoming request (used by the rate limiter).
        payload: Body containing the raw ``refresh_token``.
        response: FastAPI response object used to update the access token cookie.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope with the new ``access_token``.

    Raises:
        APIError: ``invalid_refresh_token`` / ``token_revoked`` / ``token_expired``.
    """
    ip = request.client.host if request.client else None
    result = await AuthService.refresh_access_token(
        payload.refresh_token, db, ip_address=ip
    )

    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
        samesite="lax",
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        secure=True,
        samesite="lax",
    )

    return success(
        {
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "access_token_expires_at": result["access_expires_at"].isoformat(),
            "refresh_token_expires_at": result["refresh_expires_at"].isoformat(),
            "next_step": AuthService.get_next_step(result["user"]),
        },
        message="Token refreshed",
    )


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    """Revoke a refresh token, blacklist the access token, and clear cookies.

    The access token's ``jti`` is added to the Redis blacklist so it is
    rejected by the :class:`JWTBlacklistMiddleware` for the remainder of
    its TTL, closing the window where a stolen access token could still be
    used after logout.

    Args:
        payload: Body containing the ``access_token`` and ``refresh_token``.
        response: FastAPI response object used to clear auth cookies.
        db: Async database session injected by FastAPI.

    Returns:
        A standardized success envelope acknowledging the logout.

    Raises:
        APIError: ``invalid_refresh_token`` if the refresh token is not found.
    """
    await AuthService.logout(payload.refresh_token, db)

    # Blacklist the access token so it cannot be reused
    await AuthService.blacklist_access_token_raw(payload.access_token)

    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")

    return success(message="Logged out successfully")


@router.get("/google")
@limiter.limit("10/minute")
async def google_login(request: Request):
    """Redirect the browser to Google's OAuth consent screen.

    Generates a random ``state`` token, stores it in a short-lived httponly
    cookie, and embeds it in the authorization URL. The callback verifies the
    state to prevent CSRF attacks.

    Args:
        request: Incoming request (used by the rate limiter).

    Returns:
        A 302 redirect to the Google authorization URL with state cookie set.
    """
    state = secrets.token_urlsafe(32)
    url = google_oauth.build_authorization_url(state)
    redirect = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
    )
    return redirect


@router.get("/google/callback")
@limiter.limit("10/minute")
async def google_callback(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    oauth_state: str | None = Cookie(default=None),
):
    """Handle the Google OAuth callback, issue auth tokens, and set cookies.

    Verifies the ``state`` parameter against the ``oauth_state`` cookie to
    prevent CSRF. Handles provider cancellation via the ``error`` query param.

    Args:
        request: Incoming request (used by the rate limiter).
        response: FastAPI response object used to set auth cookies.
        db: Async database session injected by FastAPI.
        code: Authorization code from Google (absent if user cancelled).
        error: Error string from Google when the flow is cancelled or fails.
        state: State token echoed back by Google.
        oauth_state: State token stored in the cookie during :func:`google_login`.

    Returns:
        A standardized success envelope with user info, tokens, and ``next_step``.

    Raises:
        APIError: 400 if the state is missing or mismatched (CSRF guard).
        APIError: 400 if Google reports a provider-side error or cancellation.
        APIError: 401 if the authorization code or access token is invalid/expired.
        APIError: 409 if the email matches an existing password-based account.
    """
    # CSRF guard — state must match the cookie set during /google
    if not oauth_state or not state or not secrets.compare_digest(oauth_state, state):
        raise APIError(
            "OAuth state mismatch",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_oauth_state",
        )
    response.delete_cookie("oauth_state")

    # Provider cancellation or error
    if error:
        raise APIError(
            "OAuth authentication was cancelled or failed",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="oauth_cancelled",
        )

    if not code:
        raise APIError(
            "Authorization code is missing",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="google_auth_error",
        )

    tokens = await google_oauth.exchange_code(code)
    google_user = await google_oauth.get_google_user(tokens["access_token"])
    user = await google_oauth.find_or_create_user(google_user, db)

    try:
        access_token = await AuthService.create_access_token(user)
        ip = request.client.host if request.client else None
        refresh_token, refresh_expires_at = await AuthService.create_refresh_token(
            db, user.id, ip_address=ip
        )
    except Exception:
        logger.exception("Failed to issue tokens for OAuth user %s", user.id)
        raise APIError(
            "Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
        )

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

    frontend_dashboard_url = f"{settings.FRONTEND_URL}/dashboard"
    return RedirectResponse(url=frontend_dashboard_url)
