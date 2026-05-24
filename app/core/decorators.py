import asyncio
import time
from functools import wraps


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
                    error_str = str(e).lower()
                    is_retryable = any(
                        keyword in error_str
                        for keyword in [
                            "timeout",
                            "connection",
                            "rate limit",
                            "quota",
                            "503",
                            "429",
                            "temporarily unavailable",
                        ]
                    )

                    if not is_retryable or attempt == max_retries - 1:
                        raise

                    sleep_time = delay * (2**attempt) + (time.time() % 1)
                    await asyncio.sleep(sleep_time)

            raise last_exception

        return wrapper

    return decorator
