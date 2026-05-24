import json

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.core.decorators import retry_with_backoff

_gemini_client = None
_GENERATION_MODEL = "gemini-2.5-flash-lite"


def _get_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            # Fallback to environment variable check in case config is loaded otherwise
            import os

            api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not configured in .env. "
                "Please add it to use the Gemini service."
            )
        _gemini_client = genai.Client(api_key=api_key).aio
    return _gemini_client


@retry_with_backoff()
async def generate_text(
    system_instruction: str,
    user_content: str,
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> str:
    response = await _get_client().models.generate_content(
        model=_GENERATION_MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text.strip()


@retry_with_backoff()
async def generate_structured_output(
    system_instruction: str,
    user_content: str,
    output_schema: type[BaseModel],
    temperature: float = 0.7,
    max_tokens: int = 1000,
) -> dict:
    response = await _get_client().models.generate_content(
        model=_GENERATION_MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=output_schema,
        ),
    )
    return json.loads(response.text)
