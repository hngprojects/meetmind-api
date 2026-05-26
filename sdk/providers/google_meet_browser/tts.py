"""Cartesia streaming TTS — replaces edge-tts file-based generation."""

from __future__ import annotations

import asyncio
import logging
import os

from sdk.config import get_sdk_settings

logger = logging.getLogger(__name__)

# Match the LiveKit agent's voice
CARTESIA_VOICE_ID = os.getenv(
    "INTERVIEWER_TTS_VOICE",
    "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"   # same voice as LiveKit agent
)
CARTESIA_MODEL = os.getenv("INTERVIEWER_TTS", "sonic-3")


async def speak_cartesia(text: str, pulse_sink: str = "meetmind_speaking") -> None:
    import cartesia

    api_key = get_sdk_settings().CARTESIA_API_KEY
    if not api_key:
        logger.error("CARTESIA_API_KEY not set — TTS disabled")
        return

    client = cartesia.AsyncCartesia(api_key=api_key)
    logger.info("Speaking via Cartesia: '%s'", text[:60])

    env = os.environ.copy()
    env["PULSE_SINK"] = pulse_sink

    # pacat streams raw PCM directly into PulseAudio — no clipping
    pacat_proc = await asyncio.create_subprocess_exec(
        "pacat",
        "--playback",
        f"--device={pulse_sink}",
        "--format=s16le",
        "--rate=44100",
        "--channels=1",
        "--latency-msec=50",   # low latency, no buffering gaps
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
    )

    ws = await client.tts.websocket()
    total_bytes = 0
    try:
        response_stream = await ws.send(
            model_id=CARTESIA_MODEL,
            transcript=text,
            voice={"id": CARTESIA_VOICE_ID},
            output_format={
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": 44100,
            },
            stream=True,
        )
        async for chunk in response_stream:
            if chunk.audio and pacat_proc.stdin:
                pacat_proc.stdin.write(chunk.audio)
                await pacat_proc.stdin.drain()
                total_bytes += len(chunk.audio)

        logger.info("TTS stream complete — %d bytes sent to pacat", total_bytes)

        if pacat_proc.stdin:
            pacat_proc.stdin.close()
            await pacat_proc.stdin.wait_closed()

        await pacat_proc.wait()
        logger.info("pacat finished cleanly")

    except Exception:
        logger.exception("Cartesia TTS error")
        if pacat_proc.returncode is None:
            pacat_proc.terminate()
    finally:
        await ws.close()
        await client.close()