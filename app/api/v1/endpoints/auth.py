from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.auth import SignupRequest, SignupResponse, ErrorResponse
from app.services.auth import AuthService

router = APIRouter()


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    db: AsyncSession = Depends(get_session)
) -> SignupResponse:
    try:
        user = await AuthService.create_user(request, db)
        return SignupResponse(
            status_code=201,
            message="Account created successfully",
            data={
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
            }
        )
    except HTTPException as e:
        if e.status_code == 400:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")