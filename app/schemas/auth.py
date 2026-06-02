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
    access_token: str
    refresh_token: str


class SignupRequest(BaseModel):
    name: str = Field(..., max_length=120, description="User's full name")
    email: EmailStr = Field(..., max_length=255, description="User's email address")
    password: str = Field(
        ..., min_length=8, max_length=255, description="User's password"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
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
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class SignupResponseData(BaseModel):
    id: str
    email: str
    name: str
    next_step: str
    onboarding_completed: bool


class LoginResponseData(BaseModel):
    id: str
    email: str
    name: str
    next_step: str
    access_token: str
    refresh_token: str
    access_token_expires_at: str
    refresh_token_expires_at: str


class RefreshResponseData(BaseModel):
    access_token: str
    refresh_token: str
    access_token_expires_at: str
    refresh_token_expires_at: str
    next_step: str


class VerifyEmailResponseData(BaseModel):
    id: str
    email: str
    next_step: str


class NextStepResponse(BaseModel):
    next_step: str  # for reset-password


class CheckEmailResponse(BaseModel):
    next_step: str  # for forgot-password
