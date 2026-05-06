import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.auth import SignupRequest, SignupResponse, SignupResponseData, ErrorResponse
from app.services.auth import AuthService

from app.core.config import settings
from app.core.exceptions import UserAlreadyExistsException

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_session)
) -> SignupResponse:
    """Register a new user, issue auth tokens, and attach cookies to the response."""
    try:
        user = await AuthService.create_user(request, db)
        access_token = await AuthService.create_access_token(user)
        refresh_token = await AuthService.create_refresh_token(db, user.id)

        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            secure=True,
            samesite="lax",
        )

        # Set Refresh Token Cookie
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
            secure=True,
            samesite="lax",
        )

        return SignupResponse(
            status_code=201,
            message="Account created successfully",
            data=SignupResponseData(
                id=str(user.id),
                email=user.email,
                name=user.name,
                access_token=access_token,
                refresh_token=refresh_token
            )
        )
    except UserAlreadyExistsException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        
    except Exception as e:
        logger.exception(f"An unexpected error occurred during signup: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")