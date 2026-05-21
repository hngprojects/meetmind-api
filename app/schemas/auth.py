"""Pydantic schemas for authentication request payloads."""

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

def _normalize_email(value: str) -> str:
    """Trim and lowercase an email string for case-insensitive identity checks."""
    return value.strip().lower()



class ForgotPasswordRequest(BaseModel):
    """Payload for requesting a password reset link."""

    email: EmailStr = Field(..., max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return _normalize_email(str(v))


class ResetPasswordRequest(BaseModel):
    """Payload for submitting a new password using a reset token."""

    token: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8, max_length=255)

    @field_validator("token")
    @classmethod
    def validate_token_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Token cannot be empty or whitespace-only")
        return v.strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Password cannot be empty or whitespace-only")
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return _normalize_email(str(v))

    @field_validator("password")
    @classmethod
    def validate_password_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Password cannot be empty or whitespace-only")
        return v


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    """Payload for logging out — both tokens required."""

    access_token: str
    refresh_token: str


class SignupRequest(BaseModel):
    """Payload for registering a new user account.

    Attributes:
        name: User's display name. Stripped of surrounding whitespace.
        email: A syntactically valid email address.
        password: Plaintext password meeting strength requirements
            enforced by :meth:`validate_password`.
    """

    name: str = Field(..., max_length=120, description="User's full name")
    email: EmailStr = Field(..., max_length=255, description="User's email address")
    password: str = Field(
        ..., min_length=8, max_length=255, description="User's password"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Reject empty/whitespace-only names, strip surrounding spaces, and
        block HTML/script injection characters.

        Args:
            v: Raw ``name`` value from the request body.

        Returns:
            The trimmed name string.

        Raises:
            ValueError: If the name is empty, whitespace-only, or contains
                unsafe characters (``< > { } & " '``).
        """
        if not v or not v.strip():
            raise ValueError("Name cannot be empty or whitespace-only")
        stripped = v.strip()
        if re.search(r"[<>{}&\"']", stripped):
            raise ValueError("Name contains invalid characters")
        return stripped

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return _normalize_email(str(v))
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Enforce minimum password strength rules.

        Requires at least 8 characters with at least one uppercase letter,
        one lowercase letter, and one digit.

        Args:
            v: Raw ``password`` value from the request body.

        Returns:
            The password unchanged when it satisfies the rules.

        Raises:
            ValueError: When any rule is violated. The message identifies
                the specific rule that failed.
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v
