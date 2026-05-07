"""Pydantic schemas for email-verification request payloads."""

from pydantic import BaseModel, EmailStr


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
