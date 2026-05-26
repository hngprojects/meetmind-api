"""Deepgram streaming STT — replaces ffmpeg+whisper chunking."""

from __future__ import annotations

import asyncio
import os
import logging
import time
from typing import Callable

from sdk.config import get_sdk_settings

logger = logging.getLogger(__name__)


class DeepgramSTT:
    """
    Streams audio from PulseAudio monitor into Deepgram's live API.
    Calls on_transcript(text) for each finalized utterance.
    """
    def __init__(self, on_transcript: Callable[[str], None]):
        self.on_transcript = on_transcript
        self._stop_event = asyncio.Event()

    async def run(self, audio_source: str = "meetmind_hearing.monitor"):
        from deepgram import (
            DeepgramClient,
            LiveTranscriptionEvents,
            LiveOptions,
        )

        api_key = get_sdk_settings().DEEPGRAM_API_KEY
        if not api_key:
            logger.error("DEEPGRAM_API_KEY not set — STT disabled")
            return

        dg = DeepgramClient(api_key)
        connection = dg.listen.asyncwebsocket.v("1")

        async def on_message(self_inner, result, **kwargs):
            try:
                alt = result.channel.alternatives[0]
                sentence = alt.transcript
                is_final = result.is_final

                if sentence:
                    if is_final:
                        logger.info(
                            "STT FINAL transcript: '%s' (confidence=%.2f)",
                            sentence,
                            alt.confidence if hasattr(alt, "confidence") else -1,
                        )
                        self.on_transcript(sentence)
                    else:
                        logger.debug("STT interim: '%s'", sentence)
            except Exception:
                logger.exception("Deepgram on_message error")

        async def on_error(self_inner, error, **kwargs):
            logger.error("Deepgram connection error: %s", error)

        async def on_close(self_inner, close, **kwargs):
            logger.warning("Deepgram connection closed: %s", close)

        async def on_open(self_inner, open, **kwargs):
            logger.info("Deepgram connection opened successfully")

        connection.on(LiveTranscriptionEvents.Transcript, on_message)
        connection.on(LiveTranscriptionEvents.Error, on_error)
        connection.on(LiveTranscriptionEvents.Close, on_close)
        connection.on(LiveTranscriptionEvents.Open, on_open)

        options = LiveOptions(
            model="nova-3",
            language="en",
            smart_format=True,
            utterance_end_ms="2000",
            vad_events=True,
            interim_results=True,
            punctuate=True,
            encoding="linear16",
            channels=1,
            sample_rate=16000,
        )

        started = await connection.start(options)
        if not started:
            logger.error("Deepgram connection failed to start — check API key and network")
            return

        logger.info("Deepgram STT connected, streaming from: %s", audio_source)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "pulse",
            "-i", audio_source,
            "-f", "s16le",
            "-ar", "16000",
            "-ac", "1",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        logger.info("ffmpeg capturing from %s (pid=%s)", audio_source, proc.pid)

        await asyncio.sleep(2)

        bytes_sent = 0
        last_log_time = time.monotonic()
        LOG_INTERVAL = 5

        try:
            while not self._stop_event.is_set():
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    logger.warning("ffmpeg stdout closed — audio source may have stopped")
                    break
                await connection.send(chunk)
                bytes_sent += len(chunk)

                now = time.monotonic()
                if now - last_log_time >= LOG_INTERVAL:
                    logger.info(
                        "STT audio stream: %d bytes sent to Deepgram (%.1f KB/s)",
                        bytes_sent,
                        bytes_sent / max(now - (last_log_time - LOG_INTERVAL + 5), 1) / 1024,
                    )
                    last_log_time = now

        finally:
            logger.info(
                "Deepgram STT stopping. Total bytes sent: %d (%.1f KB)",
                bytes_sent,
                bytes_sent / 1024,
            )
            await connection.finish()
            proc.terminate()

    def stop(self):
        self._stop_event.set()


    def __init__(self, on_transcript: Callable[[str], None]):
        self.on_transcript = on_transcript
        self._stop_event = asyncio.Event()

    async def run(self, audio_source: str = "meetmind_hearing.monitor"):
        from deepgram import (
            DeepgramClient,
            LiveTranscriptionEvents,
            LiveOptions,
        )

        api_key = get_sdk_settings().DEEPGRAM_API_KEY
        if not api_key:
            logger.error("DEEPGRAM_API_KEY not set — STT disabled")
            return

        dg = DeepgramClient(api_key)
        connection = dg.listen.asyncwebsocket.v("1")

        logger.info("Deepgram client instantiated")

        async def on_message(self_inner, result, **kwargs):
            try:
                sentence = result.channel.alternatives[0].transcript
                if sentence and result.is_final:
                    self.on_transcript(sentence)
            except Exception:
                logger.exception("Deepgram message handler error")

        connection.on(LiveTranscriptionEvents.Transcript, on_message)

        options = LiveOptions(
            model="nova-3",
            language="en",
            smart_format=True,
            utterance_end_ms="2000",   # wait 1s of silence before finalizing
            vad_events=True,
            interim_results=True,
            punctuate=True,
            encoding="linear16",
            channels=1,
            sample_rate=16000,
        )

        await connection.start(options)
        logger.info("Deepgram STT connected, recording from %s", audio_source)

        # Stream audio from PulseAudio into Deepgram
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "pulse",
            "-i", audio_source,
            "-f", "s16le",        # raw PCM, 16-bit little-endian
            "-ar", "16000",
            "-ac", "1",
            "pipe:1",             # stream to stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            while not self._stop_event.is_set():
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await connection.send(chunk)
        finally:
            await connection.finish()
            proc.terminate()
            logger.info("Deepgram STT stopped")

    def stop(self):
        self._stop_event.set()