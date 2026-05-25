import logging
from typing import Callable

logger = logging.getLogger(__name__)

async def with_fallback(providers: list[Callable], *args):
    last_error = None
    for provider in providers:
        try:
            return await provider(*args)
        except Exception as e:
            logger.warning("Provider %s failed: %s. Trying next...", provider.__name__, e)
            last_error = e
    raise RuntimeError("All providers failed.") from last_error