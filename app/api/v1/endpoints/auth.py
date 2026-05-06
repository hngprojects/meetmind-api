from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.response import APIResponse
from app.schemas.verification import (
    VerifyEmailRequest,
    ResendVerificationRequest,
)
from app.services.verification_service import VerificationService

router = APIRouter()
verification_service = VerificationService()


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_session),
) -> APIResponse:

    user, error = await verification_service.verify_email(db, payload.token)

    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "status_code": 400,
                "message": error,
                "data": None,
            },
        )

    return APIResponse(
        status_code=200,
        message="Email verified successfully",
        data={
            "id": str(user.id),
            "email": user.email,
        },
    )


@router.post("/resend-verification")
async def resend_verification(
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_session),
) -> APIResponse:

    success, error = await verification_service.resend_verification(
        db, payload.email
    )

    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "status_code": 400,
                "message": error,
                "data": None,
            },
        )

    return APIResponse(
        status_code=200,
        message="Verification email resent",
        data=None,
    )