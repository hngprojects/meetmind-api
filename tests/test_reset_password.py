"""
Test cases for password reset functionality, focusing on security implications.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
import logging

from app.core.responses import APIError
from app.models.user import (
    ActiveSession,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.services.auth import AuthService

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_password_reset_revokes_all_sessions_and_tokens(db_session):
    """
    Ensure password reset invalidates every active session.

    Expected behavior:
    - password hash changes
    - reset token becomes used
    - all refresh tokens become revoked
    - all active sessions are deleted
    """

    user = User(
        name="Itachi",
        email="itachi@test.com",
        password_hash=await AuthService.hash_password("OldPassword123"),
        is_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    logger.info("Created verified user")

    await AuthService.create_refresh_token(db_session, user.id)
    await AuthService.create_refresh_token(db_session, user.id)

    logger.info("Created two active refresh sessions")

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    # ensure at least one refresh token exists so the reset can revoke it
    await AuthService.create_refresh_token(db_session, user.id)

    logger.info("Created password reset token")

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
    ) as mock_email:
        logger.info("Executing password reset")

        await AuthService.reset_password(
            reset_token,
            "NewSecurePassword123",
            db_session,
        )

        logger.info("Password reset completed")

        mock_email.assert_awaited_once()

        logger.info("Security alert email triggered")

    result = await db_session.execute(select(User).where(User.id == user.id))

    updated_user = result.scalar_one()

    password_valid = await AuthService.verify_password(
        "NewSecurePassword123",
        updated_user.password_hash,
    )

    logger.info("New password valid: %s", password_valid)

    assert password_valid is True

    reset_result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )

    reset_record = reset_result.scalar_one()

    logger.info("Reset token used_at: %s", reset_record.used_at)

    assert reset_record.used_at is not None

    refresh_result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )

    refresh_tokens = refresh_result.scalars().all()

    revoked_states = [token.revoked for token in refresh_tokens]

    logger.info("Refresh token revoked states: %s", revoked_states)

    assert all(token.revoked for token in refresh_tokens)

    session_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    sessions = session_result.scalars().all()

    logger.info("Remaining active sessions: %s", len(sessions))

    assert len(sessions) == 0

    logger.info("Password reset security flow passed")


@pytest.mark.asyncio
async def test_old_refresh_tokens_fail_after_password_reset(db_session):
    """
    Ensure old refresh tokens cannot be reused after password reset.
    """

    user = User(
        name="Madara",
        email="madara@test.com",
        password_hash=await AuthService.hash_password("OldPassword123"),
        is_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    logger.info("Created verified user")

    old_refresh_token, _ = await AuthService.create_refresh_token(
        db_session,
        user.id,
    )

    logger.info("Created refresh token")

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    logger.info("Created password reset token")

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
    ):
        logger.info("Resetting password")

        await AuthService.reset_password(
            reset_token,
            "BrandNewPassword123",
            db_session,
        )

    logger.info("Attempting refresh using old token")

    with pytest.raises(APIError) as exc_info:
        await AuthService.refresh_access_token(
            old_refresh_token,
            db_session,
        )

    logger.info("Refresh failed with code: %s", exc_info.value.code)

    assert exc_info.value.code == "unauthorized"

    logger.info("Old refresh tokens are unusable after reset")


@pytest.mark.asyncio
async def test_invalid_reset_token_fails_generically(db_session):
    """
    Ensure invalid reset tokens do not leak validation details.
    """

    logger.info("Attempting password reset with fake token")

    with pytest.raises(APIError) as exc_info:
        await AuthService.reset_password(
            "totally-invalid-token",
            "SomePassword123",
            db_session,
        )

    error = exc_info.value

    logger.info("Error code: %s", error.code)
    logger.info("Error message: %s", error.message)

    assert error.code == "invalid_reset_token"

    assert error.message == "This reset link is invalid or has expired."

    logger.info("Generic token failure response confirmed")


@pytest.mark.asyncio
async def test_password_reset_invalidates_multiple_sessions(db_session):
    """
    Ensure password reset clears every active session.
    """

    user = User(
        name="Sasuke",
        email="sasuke@test.com",
        password_hash=await AuthService.hash_password("OldPassword123"),
        is_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    logger.info("Created verified user")

    await AuthService.create_refresh_token(db_session, user.id)
    await AuthService.create_refresh_token(db_session, user.id)
    await AuthService.create_refresh_token(db_session, user.id)

    before_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    before_sessions = before_result.scalars().all()

    logger.info("Active sessions before reset: %s", len(before_sessions))

    assert len(before_sessions) == 3

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
    ):
        logger.info("Executing password reset")

        await AuthService.reset_password(
            reset_token,
            "AnotherNewPassword123",
            db_session,
        )

    after_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    after_sessions = after_result.scalars().all()

    logger.info("Active sessions after reset: %s", len(after_sessions))

    assert len(after_sessions) == 0

    logger.info("All active sessions were invalidated")


@pytest.mark.asyncio
async def test_password_reset_succeeds_even_if_email_fails(db_session):
    """
    Ensure password reset still succeeds even if
    security alert email delivery fails.
    """

    user = User(
        name="Nagato",
        email="nagato@test.com",
        password_hash=await AuthService.hash_password(
            "OldPassword123",
        ),
        is_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    logger.info("Created reset token")

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
        side_effect=Exception("Email service failure"),
    ):
        logger.info("Resetting password while email sending fails")

        await AuthService.reset_password(
            reset_token,
            "UpdatedPassword123",
            db_session,
        )

    result = await db_session.execute(select(User).where(User.id == user.id))

    updated_user = result.scalar_one()

    password_valid = await AuthService.verify_password(
        "UpdatedPassword123",
        updated_user.password_hash,
    )

    logger.info("Password updated despite email failure: %s", password_valid)

    assert password_valid is True

    # Verify reset token was marked used and refresh tokens/sessions were revoked
    reset_result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )

    reset_record = reset_result.scalar_one()
    assert reset_record.used_at is not None

    refresh_result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )

    refresh_tokens = refresh_result.scalars().all()
    assert all(token.revoked for token in refresh_tokens)

    session_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    sessions = session_result.scalars().all()
    assert len(sessions) == 0

    logger.info("Password reset succeeds even when email delivery fails")
