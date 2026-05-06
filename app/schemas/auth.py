from pydantic import BaseModel, EmailStr, Field, field_validator
import re


class SignupRequest(BaseModel):
    name: str = Field(..., max_length=120, description="User's full name")
    email: EmailStr = Field(..., max_length=255, description="User's email address")
    password: str = Field(..., min_length=8, max_length=255, description="User's password")

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Name cannot be empty or whitespace-only')

        if re.search(r'<[^>]+>', v):
            raise ValueError('Name contains unsafe characters')
        return v.strip()

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Minimum rules: at least 8 chars, one uppercase, one lowercase, one digit
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v


class SignupResponse(BaseModel):
    status_code: int
    message: str
    data: dict


class ErrorResponse(BaseModel):
    status_code: int
    message: str