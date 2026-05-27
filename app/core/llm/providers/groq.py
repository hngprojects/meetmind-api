import json

from groq import AsyncGroq
from pydantic import BaseModel

from app.core.config import settings
from app.core.decorators import retry_with_backoff

MODEL = settings.GROQ_MODEL
_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = settings.GROQ_API_KEY
        if not api_key:
            raise ValueError("GROQ_API_KEY is not configured.")
        _client = AsyncGroq(api_key=api_key)
    return _client


@retry_with_backoff()
async def generate_text(
    system_instruction: str, user_content: str, temperature: float, max_tokens: int
) -> str:
    response = await _get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


@retry_with_backoff()
async def generate_structured_output(
    system_instruction: str,
    user_content: str,
    output_schema: type[BaseModel],
    temperature: float,
    max_tokens: int,
) -> dict:
    response = await _get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = json.loads(response.choices[0].message.content)
    return output_schema.model_validate(raw).model_dump()
