from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from sdk.config import get_sdk_settings
from sdk.db import get_sdk_db
from sdk.providers.zoom_rtms.oauth import ZoomOAuthClient, ZoomOAuthError
from sdk.providers.zoom_rtms.oauth_state import (
    ZoomOAuthStateError,
    create_oauth_state,
    validate_oauth_state,
)
from sdk.providers.zoom_rtms.webhook import handle_zoom_webhook
from sdk.providers.zoom_rtms.webhook_security import verify_zoom_signature
from sdk.schemas import OAuthAuthorizeURLResponse, OAuthCallbackResponse

router = APIRouter()


@router.post("/rtms/webhook")
async def zoom_rtms_webhook(request: Request, db: Session = Depends(get_sdk_db)):
    settings = get_sdk_settings()
    raw_body = await request.body()
    if not verify_zoom_signature(
        raw_body=raw_body,
        timestamp=request.headers.get("x-zm-request-timestamp"),
        signature=request.headers.get("x-zm-signature"),
        secret_token=settings.zoom_webhook_secret_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Zoom webhook signature",
        )

    payload = await request.json()
    return await run_in_threadpool(handle_zoom_webhook, db=db, payload=payload)


@router.get("/oauth/authorize-url", response_model=OAuthAuthorizeURLResponse)
def zoom_oauth_authorize_url():
    settings = get_sdk_settings()
    try:
        state = create_oauth_state(settings.zoom_state_secret)
    except ZoomOAuthStateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.zoom_client_id,
            "redirect_uri": settings.zoom_oauth_redirect_url,
            "state": state,
        }
    )
    return OAuthAuthorizeURLResponse(
        authorization_url=f"https://zoom.us/oauth/authorize?{query}",
        state=state,
    )


@router.post("/oauth/callback", response_model=OAuthCallbackResponse)
@router.get("/oauth/callback", response_model=OAuthCallbackResponse)
def zoom_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: Session = Depends(get_sdk_db),
):
    token_stored = False
    if code:
        try:
            validate_oauth_state(state, get_sdk_settings().zoom_state_secret)
            ZoomOAuthClient(db).exchange_code(code)
        except ZoomOAuthStateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ZoomOAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        token_stored = True
    return OAuthCallbackResponse(
        received=True,
        code_present=bool(code),
        state=state,
        token_stored=token_stored,
    )
