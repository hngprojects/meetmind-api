from app.core.config import settings
from app.core.llm.providers import gemini, openrouter, groq

_PROVIDER_MAP = {
    "gemini": gemini,
    "openrouter": openrouter,
    "groq": groq,
}

def _get_text_providers():
    return [_PROVIDER_MAP[p].generate_text for p in settings.LLM_PROVIDERS]

def _get_structured_providers():
    return [_PROVIDER_MAP[p].generate_structured_output for p in settings.LLM_PROVIDERS]