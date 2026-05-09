"""Transactional email delivery via Resend."""

from __future__ import annotations

import logging

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY


async def send_password_reset_email(email: str, name: str | None, token: str) -> None:
    """Send a password reset link to a registered user.

    Args:
        email: Recipient email address.
        name: Recipient's display name, used in the greeting.
        token: Raw reset token to embed in the link.
    """
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    greeting = f"Hi {name}," if name else "Hi,"

    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": email,
            "subject": "Reset your MeetMind password",
            "html": f"""
                <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
                    <h2 style="color:#1a1a1a">Reset your password</h2>
                    <p>{greeting}</p>
                    <p>Click the button below to reset your password.
                       This link expires in 60 minutes.</p>
                    <a href="{reset_url}"
                       style="display:inline-block;padding:12px 24px;background:#6366f1;
                              color:#fff;border-radius:6px;text-decoration:none;font-weight:600">
                        Reset password
                    </a>
                    <p style="margin-top:24px;color:#666;font-size:13px">
                        If you didn't request a password reset, you can ignore this email.
                        Your password will not be changed.
                    </p>
                </div>
            """,
        })
    except Exception:
        logger.exception("Failed to send password reset email to %s", email)
        raise


async def send_verification_email(email: str, name: str | None, token: str) -> None:
    """Send an email verification link to a newly registered user.

    Args:
        email: Recipient email address.
        name: Recipient's display name, used in the greeting.
        token: Raw verification token to embed in the link.
    """
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    greeting = f"Hi {name}," if name else "Hi,"

    try:
        resend.Emails.send({
            "from": settings.EMAIL_FROM,
            "to": email,
            "subject": "Verify your MeetMind email",
            "html": f"""
                <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
                    <h2 style="color:#1a1a1a">Verify your email</h2>
                    <p>{greeting}</p>
                    <p>Click the button below to verify your email address.
                       This link expires in 30 minutes.</p>
                    <a href="{verify_url}"
                       style="display:inline-block;padding:12px 24px;background:#6366f1;
                              color:#fff;border-radius:6px;text-decoration:none;font-weight:600">
                        Verify email
                    </a>
                    <p style="margin-top:24px;color:#666;font-size:13px">
                        If you didn't create a MeetMind account, you can ignore this email.
                    </p>
                </div>
            """,
        })
    except Exception:
        logger.exception("Failed to send verification email to %s", email)
        # Re-raise so callers can surface a safe 500 — provider details stay in logs only.
        raise
