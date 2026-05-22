"""FastAPI middleware that rejects requests bearing a blacklisted JWT."""

import logging

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.redis import is_token_blacklisted

logger = logging.getLogger(__name__)


class JWTBlacklistMiddleware(BaseHTTPMiddleware):
    """Intercept every request and reject blacklisted access tokens.

    Extracts the JWT from the ``access_token`` cookie or the
    ``Authorization: Bearer`` header, decodes the ``jti`` claim *without*
    verifying the signature (the downstream dependency does full validation),
    and checks the Redis blacklist. If the token's ``jti`` is present in
    Redis, a 401 is returned before the request reaches any route handler.
    """

    async def dispatch(self, request: Request, call_next):
        token = self._extract_token(request)
        if token:
            jti = self._extract_jti(token)
            if jti and await is_token_blacklisted(jti):
                logger.info("Rejected request with blacklisted token jti=%s", jti)
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "message": "Token has been revoked",
                        "data": None,
                        "meta": None,
                    },
                )
        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        """Return the raw JWT from cookie or Authorization header."""
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            return cookie_token

        auth = request.headers.get("authorization", "")
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]

        return None

    @staticmethod
    def _extract_jti(token: str) -> str | None:
        """Decode the ``jti`` claim without signature verification."""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_exp": False},
            )
            return payload.get("jti")
        except Exception:
            return None
