"""Audio transcription with Gemini (primary) → Groq Whisper (fallback)."""

import logging
from io import BytesIO

from google import genai
from google.genai import types
from groq import AsyncGroq

from app.core.config import settings
from app.core.llm.fallback import with_fallback

logger = logging.getLogger(__name__)

_MIME_MAP = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


async def _transcribe_gemini(
    audio_content: bytes, filename: str, language: str | None = None
) -> str:
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    mime_type = _MIME_MAP.get(ext, "audio/webm")
    client = genai.Client(api_key=settings.GEMINI_API_KEY).aio
    response = await client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=[
            "Transcribe the speech in this audio. Return only the transcribed text.",
            types.Part.from_bytes(data=audio_content, mime_type=mime_type),
        ],
    )
    return response.text.strip()


async def _transcribe_groq(
    audio_content: bytes, filename: str, language: str | None = None
) -> str:
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not configured")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    mime_type = _MIME_MAP.get(ext, "audio/webm")
    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    transcript = await client.audio.transcriptions.create(
        model="whisper-large-v3",
        file=(filename, BytesIO(audio_content), mime_type),
        language=language,
        response_format="text",
    )
    return transcript.strip()


async def transcribe_audio(
    audio_content: bytes,
    filename: str = "audio.webm",
    language: str | None = None,
) -> str:
    """Transcribe audio using Gemini, falling back to Groq Whisper."""
    return await with_fallback(
        [_transcribe_gemini, _transcribe_groq],
        audio_content,
        filename,
        language,
    )
