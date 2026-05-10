"""Transactional email delivery via Resend."""

from __future__ import annotations

import logging
from html import escape as escape_html

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY


async def _send_email(email: str, subject: str, html: str) -> None:
    """Centralized send helper that uses the async Resend client.

    Keeps the try/except and logging in one place so callers remain thin.
    """
    try:
        await resend.Emails.send_async(
            {
                "from": settings.EMAIL_FROM,
                "to": email,
                "subject": subject,
                "html": html,
            }
        )
    except Exception:
        logger.exception("Failed to send email to %s", email)
        raise


async def send_password_reset_email(email: str, name: str | None, token: str) -> None:
    """Send a password reset link to a registered user.

    Args:
        email: Recipient email address.
        name: Recipient's display name, used in the greeting.
        token: Raw reset token to embed in the link.
    """
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    safe_name = escape_html(name) if name else None
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    html = f"""
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
                        If you didn't request a password reset, 
                        you can ignore this email.
                        Your password will not be changed.
                    </p>
                </div>
            """

    await _send_email(email, "Reset your MeetMind password", html)


async def send_verification_email(email: str, name: str | None, token: str) -> None:
    """Send an email verification link to a newly registered user.

    Args:
        email: Recipient email address.
        name: Recipient's display name, used in the greeting.
        token: Raw verification token to embed in the link.
    """
    verify_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={token}"
    safe_name = escape_html(name) if name else None
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    html = f"""
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
                        If you didn't create a MeetMind account, 
                        you can ignore this email.
                    </p>
                </div>
            """

    await _send_email(email, "Verify your MeetMind email", html)


async def send_password_reset_security_alert(
    email: str,
    name: str | None,
) -> None:
    """Notify the user that all active sessions were revoked.

    Args:
        email: Recipient email address.
        name: Recipient display name.
    """
    safe_name = escape_html(name) if name else None
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    html = f"""
                <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
                    <h2 style="color:#1a1a1a">Password changed successfully</h2>

                    <p>{greeting}</p>

                    <p>
                        Your MeetMind password was successfully changed.
                    </p>

                    <p>
                        For security reasons, all active sessions on your
                        account have been signed out and will require login again.
                    </p>

                    <p style="margin-top:24px;color:#666;font-size:13px">
                        If you did not perform this action, 
                        please contact support immediately.
                    </p>
                </div>
            """

    await _send_email(email, "Your MeetMind password was changed", html)
