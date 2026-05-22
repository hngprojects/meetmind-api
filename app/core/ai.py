import google.genai as genai

from app.core.config import settings


async def generate_with_gemini(
    prompt: str, model: str = "models/gemini-2.5-flash-lite"
):
    """
    Call Gemini asynchronously with a prompt and return the response.
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY).aio
    response = await client.models.generate_content(
        model=model,
        contents=prompt,
    )
    return response
