"""Transactional email delivery via Resend."""

from __future__ import annotations

import logging
from html import escape as escape_html
from typing import Optional

import resend
from fastapi import BackgroundTasks

from app.core.config import settings
from app.services.email_renderer import render_template

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY

if settings.MOCK_EMAILS:
    logger.info(
        "Mock email delivery enabled (MOCK_EMAILS=true) — emails will be logged,"
        " not sent"
    )


async def _send_email(email: str, subject: str, html: str) -> None:
    """Centralized send helper that uses the async Resend client.

    Keeps the try/except and logging in one place so callers remain thin.
    """
    # For dev environments we can bypass the external provider and simply
    # log the email payload for inspection. This keeps background tasks and
    # caller behavior identical while avoiding network calls.
    if settings.MOCK_EMAILS:
        logger.info("[MOCK EMAIL] to=%s subject=%s", email, subject)
        logger.debug("[MOCK EMAIL] html=\n%s", html)
        return

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


async def send_password_reset_email(
    email: str,
    name: str | None,
    token: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    safe_name = escape_html(name) if name else None
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    html = render_template(
        "emails/reset_password.html", reset_url=reset_url, greeting=greeting
    )

    if background_tasks:
        background_tasks.add_task(
            _send_email, email, "Reset your MeetMind password", html
        )
    else:
        await _send_email(email, "Reset your MeetMind password", html)


async def send_welcome_email(
    email: str,
    name: str | None,
    action_url: str | None = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    dashboard_url = action_url or f"{settings.FRONTEND_URL.rstrip('/')}/dashboard"
    display_name = name or "there"

    html = render_template(
        "emails/welcome.html", name=display_name, action_url=dashboard_url
    )

    if background_tasks:
        background_tasks.add_task(_send_email, email, "Welcome to MeetMind", html)
    else:
        await _send_email(email, "Welcome to MeetMind", html)


async def send_account_deletion_email(
    email: str,
    name: str | None,
    confirm_url: str,
    cancel_url: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    display_name = name or "there"

    html = render_template(
        "emails/account_deletion.html",
        name=display_name,
        confirm_url=confirm_url,
        cancel_url=cancel_url,
    )

    if background_tasks:
        background_tasks.add_task(
            _send_email, email, "Account deletion requested", html
        )
    else:
        await _send_email(email, "Account deletion requested", html)


async def send_verification_email(
    email: str,
    name: str | None,
    token: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    verify_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={token}"
    safe_name = escape_html(name) if name else None
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    html = render_template(
        "emails/verify_email.html", verify_url=verify_url, greeting=greeting
    )

    if background_tasks:
        background_tasks.add_task(
            _send_email, email, "Verify your MeetMind email", html
        )
    else:
        await _send_email(email, "Verify your MeetMind email", html)


async def send_password_reset_security_alert(
    email: str, name: str | None, background_tasks: Optional[BackgroundTasks] = None
) -> None:
    safe_name = escape_html(name) if name else None
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    html = render_template(
        "emails/password_changed_security_alert.html", greeting=greeting
    )

    if background_tasks:
        background_tasks.add_task(
            _send_email, email, "Your MeetMind password was changed", html
        )
    else:
        await _send_email(email, "Your MeetMind password was changed", html)
