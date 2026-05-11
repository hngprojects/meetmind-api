"""Async Redis client singleton and JWT blacklist utilities."""

import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

redis_client: redis.Redis = redis.from_url(
    str(settings.REDIS_URL), decode_responses=True
)

_BLACKLIST_PREFIX = "jwt:blacklist:jti:"


async def blacklist_token(jti: str, expires_in: int) -> None:
    """Add a JWT ID to the Redis blacklist.

    The key auto-expires after ``expires_in`` seconds so no manual cleanup
    is needed — the entry disappears when the token would have expired anyway.

    Args:
        jti: The ``jti`` claim from the access token.
        expires_in: Remaining seconds until the token expires (used as TTL).
    """
    if expires_in <= 0:
        return
    key = f"{_BLACKLIST_PREFIX}{jti}"
    try:
        await redis_client.setex(key, expires_in, "1")
    except redis.RedisError:
        logger.exception("Failed to blacklist token jti=%s", jti)


async def is_token_blacklisted(jti: str) -> bool:
    """Check whether a JWT ID has been blacklisted.

    Args:
        jti: The ``jti`` claim to look up.

    Returns:
        ``True`` if the token is blacklisted, ``False`` otherwise.
        Returns ``False`` on Redis connection errors (fail-open).
    """
    key = f"{_BLACKLIST_PREFIX}{jti}"
    try:
        return await redis_client.exists(key) == 1
    except redis.RedisError:
        logger.exception("Redis lookup failed for jti=%s", jti)
        return False
