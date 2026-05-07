import pytest
from sqlalchemy import select

from app.models.user import User
from app.models.email_verification import EmailVerificationToken
from app.services.verification_service import VerificationService


@pytest.mark.asyncio
async def test_create_verification_token(db_session):
    service = VerificationService()

    user = User(email="test1@example.com")
    db_session.add(user)
    await db_session.commit()

    token = await service.create_verification_token(db_session, user.id)

    assert token is not None

    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    db_token = result.scalar_one_or_none()

    assert db_token is not None
    assert db_token.token_hash is not None


@pytest.mark.asyncio
async def test_verify_email_success(db_session):
    service = VerificationService()

    user = User(email="test2@example.com", is_verified=False)
    db_session.add(user)
    await db_session.commit()

    token = await service.create_verification_token(db_session, user.id)

    verified_user, error = await service.verify_email(db_session, token)

    assert error is None
    assert verified_user.is_verified is True


@pytest.mark.asyncio
async def test_verify_email_invalid_token(db_session):
    service = VerificationService()

    user, error = await service.verify_email(db_session, "invalidtoken")

    assert user is None
    assert error == "Invalid verification token"


@pytest.mark.asyncio
async def test_resend_verification(db_session):
    service = VerificationService()

    user = User(email="test3@example.com", is_verified=False)
    db_session.add(user)
    await db_session.commit()

    success, error = await service.resend_verification(
        db_session, user.email
    )

    assert success is True
    assert error is None

    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id
        )
    )
    tokens = result.scalars().all()

    assert len(tokens) > 0