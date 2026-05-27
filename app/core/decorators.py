import asyncio
from functools import wraps
from random import uniform

import httpx

RETRYABLE_KEYWORDS = [
    "timeout",
    "connection",
    "rate limit",
    "quota",
    "temporarily unavailable",
    "resource_exhausted",
    "service unavailable",
    "too many requests",
]
RETRYABLE_STATUS_CODES = {429, 503, 504}


def _is_retryable(e: Exception) -> bool:
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in RETRYABLE_STATUS_CODES
    error_str = str(e).lower()
    return any(kw in error_str for kw in RETRYABLE_KEYWORDS)


def retry_with_backoff(max_retries: int = 3, initial_delay: float = 1.0):
    """Retry decorator with exponential backoff for transient errors"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if not _is_retryable(e) or attempt == max_retries - 1:
                        raise

                    sleep_time = delay * (2**attempt) + uniform(0, 1)
                    await asyncio.sleep(sleep_time)

            raise last_exception

        return wrapper

    return decorator
