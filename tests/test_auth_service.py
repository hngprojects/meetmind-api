from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import jwt

from app.core.config import settings
from app.models.user import User
from app.services.auth import AuthService


def make_user(**kwargs):
    user = MagicMock(spec=User)
    user.id = kwargs.get("id", uuid4())
    user.email = kwargs.get("email", "john@example.com")
    user.name = kwargs.get("name", "John Doe")
    return user


class TestCreateAccessToken:
    @pytest.mark.asyncio
    async def test_returns_unique_token_on_same_second(self):
        user = make_user()
        token1 = await AuthService.create_access_token(user)
        token2 = await AuthService.create_access_token(user)
        assert token1 != token2

    @pytest.mark.asyncio
    async def test_jti_claim_present_and_nonempty(self):
        user = make_user()
        token = await AuthService.create_access_token(user)
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload.get("jti")
