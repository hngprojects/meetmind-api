"""
Test cases for password reset functionality, focusing on security implications.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.responses import APIError
from app.models.user import (
    ActiveSession,
    PasswordResetToken,
    RefreshToken,
    User,
)
from app.services.auth import AuthService


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

    print("\n[SETUP] Created verified user")

    await AuthService.create_refresh_token(db_session, user.id)
    await AuthService.create_refresh_token(db_session, user.id)

    print("[SETUP] Created two active refresh sessions")

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    # create at least one refresh token/session so there is something to revoke
    await AuthService.create_refresh_token(db_session, user.id)

    print("[SETUP] Created password reset token")

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
    ) as mock_email:
        print("[ACTION] Executing password reset")

        await AuthService.reset_password(
            reset_token,
            "NewSecurePassword123",
            db_session,
        )

        print("[ASSERT] Password reset completed")

        mock_email.assert_awaited_once()

        print("[CHECK] Security alert email was triggered")

    result = await db_session.execute(select(User).where(User.id == user.id))

    updated_user = result.scalar_one()

    password_valid = await AuthService.verify_password(
        "NewSecurePassword123",
        updated_user.password_hash,
    )

    print(f"[CHECK] New password valid: {password_valid}")

    assert password_valid is True

    reset_result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )

    reset_record = reset_result.scalar_one()

    print(f"[CHECK] Reset token used_at: {reset_record.used_at}")

    assert reset_record.used_at is not None

    refresh_result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )

    refresh_tokens = refresh_result.scalars().all()

    revoked_states = [token.revoked for token in refresh_tokens]

    print(f"[CHECK] Refresh token revoked states: {revoked_states}")

    assert all(token.revoked for token in refresh_tokens)

    session_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    sessions = session_result.scalars().all()

    print(f"[CHECK] Remaining active sessions: {len(sessions)}")

    assert len(sessions) == 0

    print("[SUCCESS] Password reset security flow works correctly")


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

    print("\n[SETUP] Created verified user")

    old_refresh_token, _ = await AuthService.create_refresh_token(
        db_session,
        user.id,
    )

    print("[SETUP] Created refresh token")

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    print("[SETUP] Created password reset token")

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
    ):
        print("[ACTION] Resetting password")

        await AuthService.reset_password(
            reset_token,
            "BrandNewPassword123",
            db_session,
        )

    print("[ACTION] Attempting refresh using old token")

    with pytest.raises(APIError) as exc_info:
        await AuthService.refresh_access_token(
            old_refresh_token,
            db_session,
        )

    print(f"[CHECK] Refresh failed with code: {exc_info.value.code}")

    assert exc_info.value.code == "unauthorized"

    print("[SUCCESS] Old refresh tokens are unusable after reset")


@pytest.mark.asyncio
async def test_invalid_reset_token_fails_generically(db_session):
    """
    Ensure invalid reset tokens do not leak validation details.
    """

    print("\n[ACTION] Attempting password reset with fake token")

    with pytest.raises(APIError) as exc_info:
        await AuthService.reset_password(
            "totally-invalid-token",
            "SomePassword123",
            db_session,
        )

    error = exc_info.value

    print(f"[CHECK] Error code: {error.code}")
    print(f"[CHECK] Error message: {error.message}")

    assert error.code == "invalid_reset_token"

    assert error.message == "This reset link is invalid or has expired."

    print("[SUCCESS] Generic token failure response confirmed")


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

    print("\n[SETUP] Created verified user")

    await AuthService.create_refresh_token(db_session, user.id)
    await AuthService.create_refresh_token(db_session, user.id)
    await AuthService.create_refresh_token(db_session, user.id)

    before_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    before_sessions = before_result.scalars().all()

    print(f"[CHECK] Active sessions before reset: {len(before_sessions)}")

    assert len(before_sessions) == 3

    reset_token = await AuthService.create_password_reset_token(
        db_session,
        user,
    )

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
    ):
        print("[ACTION] Executing password reset")

        await AuthService.reset_password(
            reset_token,
            "AnotherNewPassword123",
            db_session,
        )

    after_result = await db_session.execute(
        select(ActiveSession).where(ActiveSession.user_id == user.id)
    )

    after_sessions = after_result.scalars().all()

    print(f"[CHECK] Active sessions after reset: {len(after_sessions)}")

    assert len(after_sessions) == 0

    print("[SUCCESS] All active sessions were invalidated")


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

    print("\n[SETUP] Created reset token")

    with patch(
        "app.services.auth.send_password_reset_security_alert",
        new_callable=AsyncMock,
        side_effect=Exception("Email service failure"),
    ):
        print("[ACTION] Resetting password with failing email service")

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

    print(f"[CHECK] Password updated despite email failure: {password_valid}")

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

    print("[SUCCESS] Password reset succeeds even if email sending fails")
