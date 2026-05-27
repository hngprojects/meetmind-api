from pydantic import BaseModel

from app.core.llm.fallback import with_fallback
from app.core.llm.providers import _get_structured_providers, _get_text_providers


async def generate_text(
    system_instruction: str,
    user_content: str,
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> str:
    return await with_fallback(
        _get_text_providers(),
        system_instruction,
        user_content,
        temperature,
        max_tokens,
    )


async def generate_structured_output(
    system_instruction: str,
    user_content: str,
    output_schema: type[BaseModel],
    temperature: float = 0.7,
    max_tokens: int = 1000,
) -> dict:
    return await with_fallback(
        _get_structured_providers(),
        system_instruction,
        user_content,
        output_schema,
        temperature,
        max_tokens,
    )
