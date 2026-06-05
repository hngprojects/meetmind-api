import json

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.decorators import retry_with_backoff

MODEL = settings.GEMINI_MODEL


def _make_client():
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=api_key).aio


_client = _make_client()


@retry_with_backoff()
async def generate_text(
    system_instruction: str, user_content: str, temperature: float, max_tokens: int
) -> str:
    response = await _client.models.generate_content(
        model=MODEL,
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
    system_instruction, user_content, output_schema, temperature, max_tokens
) -> dict:
    response = await _client.models.generate_content(
        model=MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        ),
    )
    raw = json.loads(response.text)
    return output_schema.model_validate(raw).model_dump()
