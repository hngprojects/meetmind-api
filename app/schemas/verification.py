"""Pydantic schemas for email-verification request payloads."""

from pydantic import BaseModel, EmailStr, field_validator


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class VerifyEmailRequest(BaseModel):
    """Payload for redeeming an email-verification token.

    Attributes:
        token: Raw token string previously delivered to the user.
    """

    token: str


class ResendVerificationRequest(BaseModel):
    """Payload for requesting a fresh verification email.

    Attributes:
        email: Email address of the account requesting a new token.
    """

    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return _normalize_email(str(v))
