from google import genai
from google.genai import types

from app.core.config import settings


_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY).aio
_GENERATION_MODEL = "gemini-2.0-flash"


async def generate_text(
    system_instruction: str,
    user_content: str,
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> str:
    response = await _gemini_client.models.generate_content(
        model=_GENERATION_MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text.strip()
