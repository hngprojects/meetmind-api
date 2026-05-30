import logging

import pytest

from app.services import email_service


@pytest.fixture(autouse=True)
def enable_mock_emails(monkeypatch):
    monkeypatch.setattr(email_service.settings, "MOCK_EMAILS", True)
    monkeypatch.setattr(email_service.settings, "FRONTEND_URL", "https://app.meetmind.test")


@pytest.mark.asyncio
async def test_send_welcome_email_renders_without_error(caplog):
    caplog.set_level(logging.INFO, logger="app.services.email_service")

    await email_service.send_welcome_email(
        "user@example.com",
        "Avery",
        "https://app.meetmind.test/dashboard",
    )

    assert "[MOCK EMAIL] to=user@example.com subject=Welcome to MeetMind" in caplog.text


@pytest.mark.asyncio
async def test_send_reset_password_email_renders_without_error(caplog):
    caplog.set_level(logging.INFO, logger="app.services.email_service")

    await email_service.send_password_reset_email(
        "user@example.com",
        "Avery",
        "reset-token",
    )

    assert (
        "[MOCK EMAIL] to=user@example.com subject=Reset your MeetMind password"
        in caplog.text
    )


@pytest.mark.asyncio
async def test_send_account_deletion_email_renders_without_error(caplog):
    caplog.set_level(logging.INFO, logger="app.services.email_service")

    await email_service.send_account_deletion_email(
        "user@example.com",
        "Avery",
        "https://app.meetmind.test/delete/confirm",
        "https://app.meetmind.test/delete/cancel",
    )

    assert (
        "[MOCK EMAIL] to=user@example.com subject=Account deletion requested"
        in caplog.text
    )