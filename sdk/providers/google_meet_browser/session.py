import asyncio
import os
import tempfile
from datetime import datetime
from typing import Callable, Optional
import logging

from sdk.providers.google_meet_browser.stt import DeepgramSTT
from sdk.providers.google_meet_browser.tts import speak_cartesia

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Google_Meet_Session")

from playwright.async_api import async_playwright

try:
    import faster_whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import edge_tts
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

from .audio import (
    HEARING_SINK, SPEAKING_SINK, VIRTUAL_MIC,
    route_sink_inputs_to_hearing, get_env_for_chromium,
)
from .events import BotStatus, TranscriptEvent, StatusEvent, ErrorEvent


class GoogleMeetSession:
    def __init__(
        self,
        session_id: str,
        meeting_url: str,
        bot_name: str,
        on_event: Callable,
        interview_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.meeting_url = meeting_url
        self.bot_name = bot_name
        self.on_event = on_event
        self.interview_id = interview_id
        self.status = BotStatus.LAUNCHING
        self._stop_event = asyncio.Event()
        self._playwright = None
        self._context = None
        self._page = None
        self._stt_model = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self):
        try:
            await self._launch_browser()
            await self._join_meet()
            await self._emit_status(BotStatus.IN_MEETING)
            await self._unmute_mic()
            await asyncio.sleep(3)

            await asyncio.gather(
                self._stt_loop(),
                self._caption_loop(),
                self._audio_routing_loop(),
                self._audio_health_loop(),
                self._stop_event.wait(),
            )
        except Exception as e:
            import traceback
            await self._emit_error(str(e), traceback.format_exc())
        finally:
            await self._cleanup()

    async def stop(self):
        self._stop_event.set()

    # async def speak(self, text: str):
    #     await self._emit_transcript(
    #         speaker=self.bot_name,
    #         text=text,
    #         source="bot",
    #         role="agent",
    #     )
    #     if not HAS_TTS:
    #         return

    #     with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
    #         out_path = f.name
    #     try:
    #         communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
    #         await communicate.save(out_path)
    #         env = get_env_for_chromium()
    #         env["PULSE_SINK"] = SPEAKING_SINK
    #         proc = await asyncio.create_subprocess_exec(
    #             "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
    #             out_path, env=env,
    #             stdout=asyncio.subprocess.DEVNULL,
    #             stderr=asyncio.subprocess.DEVNULL,
    #         )
    #         await proc.wait()
    #     finally:
    #         try:
    #             os.unlink(out_path)
    #         except Exception:
    #             pass

    async def speak(self, text: str):
        """Speak text via Cartesia TTS into the meeting."""
        await self._emit_transcript(
            text=text,
            speaker=self.bot_name,
            source="bot",
            role="agent",
        )
        await speak_cartesia(text, pulse_sink="meetmind_speaking")

    # ── Browser ───────────────────────────────────────────────────────────────

    async def _launch_browser(self):
        self._playwright = await async_playwright().start()
        env = get_env_for_chromium()

        for cmd in [
            ["pactl", "set-source-mute", VIRTUAL_MIC, "0"],
            ["pactl", "set-source-volume", VIRTUAL_MIC, "65536"],
            ["pactl", "set-sink-mute", SPEAKING_SINK, "0"],
        ]:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

        from sdk.config import get_sdk_settings
        settings = get_sdk_settings()

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=settings.CHROMIUM_PROFILE_DIR,
            headless=False,
            permissions=["camera", "microphone"],
            env=env,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--use-fake-ui-for-media-stream",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--no-first-run",
                "--start-maximized",
                "--disable-gpu",
            ],
        )

        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };

            const _origGUM = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = async (constraints) => {
                if (constraints && constraints.audio) {
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    const virtualMic = devices.find(d =>
                        d.kind === 'audioinput' &&
                        (d.label.includes('MeetMind') || d.label.includes('meetmind'))
                    );
                    if (virtualMic) {
                        constraints.audio = { deviceId: { exact: virtualMic.deviceId } };
                    }
                }
                return _origGUM(constraints);
            };
        """)
        self._page = await self._context.new_page()

    async def _join_meet(self):
        await self._emit_status(BotStatus.JOINING)
        await self._page.goto(self.meeting_url, wait_until="domcontentloaded")

        for text in ["Got it", "Dismiss", "No thanks", "Continue without signing in"]:
            try:
                await self._page.click(f"text={text}", timeout=3000)
                await asyncio.sleep(0.5)
                break
            except Exception:
                continue

        await asyncio.sleep(4)

        for text in ["Continue without signing in", "Use without an account", "Join as guest"]:
            try:
                await self._page.click(f"text={text}", timeout=2000)
                await asyncio.sleep(1)
                break
            except Exception:
                continue
        
        try:
            name_input = await self._page.wait_for_selector(
                'input[placeholder*="name" i], input[aria-label*="name" i]',
                timeout=6000,
            )
            await name_input.click()
            await name_input.fill("")
            await name_input.type("MeetMind", delay=80)
            await asyncio.sleep(1)
        except Exception as e:
            await logger.info("log", f"Name input not found: {e}")


        for text in ["Ask to join", "Join now", "Join"]:
            try:
                await self._page.click(f"text={text}", timeout=5000)
                await asyncio.sleep(3)
                break
            except Exception:
                continue


    async def _unmute_mic(self):
        for selector in [
            '[aria-label*="Turn on microphone"]',
            '[aria-label*="Unmute microphone"]',
        ]:
            try:
                btn = await self._page.wait_for_selector(selector, timeout=3000)
                if btn:
                    await btn.click()
                    return
            except Exception:
                continue

        await self._page.evaluate("""
            () => {
                for (const btn of document.querySelectorAll('button')) {
                    const label = btn.getAttribute('aria-label') || '';
                    if (label.toLowerCase().includes('turn on') &&
                        label.toLowerCase().includes('microphone')) {
                        btn.click(); return;
                    }
                }
            }
        """)

    # ── Audio loops ───────────────────────────────────────────────────────────

    async def _audio_routing_loop(self):
        await asyncio.sleep(5)
        while not self._stop_event.is_set():
            try:
                await route_sink_inputs_to_hearing()
            except Exception:
                pass
            await asyncio.sleep(1)

    async def _caption_loop(self):
        last_seen = ""
        while not self._stop_event.is_set():
            try:
                captions = await self._page.query_selector_all(
                    '[jsname="tgaKEf"], [data-message-text]'
                )
                for el in captions:
                    text = (await el.inner_text()).strip()
                    if text and text != last_seen:
                        last_seen = text
                        await self._emit_transcript(
                            text, "(caption)", "caption", "human"
                        )
            except Exception:
                pass
            await asyncio.sleep(1.5)

    # async def _stt_loop(self):
    #     if not HAS_WHISPER:
    #         return

    #     loop = asyncio.get_event_loop()
    #     await loop.run_in_executor(None, self._load_stt_model)

    #     while not self._stop_event.is_set():
    #         with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
    #             chunk_path = f.name

    #         proc = await asyncio.create_subprocess_exec(
    #             "ffmpeg", "-y",
    #             "-f", "pulse",
    #             "-i", f"{HEARING_SINK}.monitor",
    #             "-t", "4",
    #             "-af", "highpass=f=200,lowpass=f=3000,loudnorm",
    #             "-ar", "16000", "-ac", "1",
    #             chunk_path,
    #             stdout=asyncio.subprocess.DEVNULL,
    #             stderr=asyncio.subprocess.DEVNULL,
    #         )
    #         await proc.wait()

    #         if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 1000:
    #             text = await loop.run_in_executor(None, self._transcribe, chunk_path)
    #             if text.strip():
    #                 await self._emit_transcript(
    #                     text, "(audio)", "stt", "human"
    #                 )
    #         try:
    #             os.unlink(chunk_path)
    #         except Exception:
    #             pass

    # def _load_stt_model(self):
    #     if not self._stt_model:
    #         self._stt_model = faster_whisper.WhisperModel(
    #             "base", device="cpu", compute_type="int8"
    #         )

    async def _stt_loop(self):
        loop = asyncio.get_event_loop()

        def on_transcript(text: str):
            # This is called from Deepgram's async handler — already on the event loop
            # Use call_soon_threadsafe only if called from another thread
            asyncio.run_coroutine_threadsafe(
                self._emit_transcript(text, "(audio)", "stt", "human"),
                loop,
            )

        self._stt = DeepgramSTT(on_transcript=on_transcript)

        stt_task = asyncio.create_task(
            self._stt.run(audio_source="meetmind_hearing.monitor")
        )
        await self._stop_event.wait()
        self._stt.stop()
        stt_task.cancel()
        try:
            await stt_task
        except asyncio.CancelledError:
            pass

    def _transcribe(self, audio_path: str) -> str:
        segments, _ = self._stt_model.transcribe(
            audio_path, language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
        )
        hallucinations = {
            "You", "you", "Thank you.", "Thanks.",
            "Bye.", ".", "...", "Thank you for watching."
        }
        return " ".join(
            s.text.strip() for s in segments
            if s.text.strip() and s.text.strip() not in hallucinations
        )
    
    async def _audio_health_loop(self):
        """Log audio routing state every 15 seconds."""
        from .audio import log_sink_levels
        await asyncio.sleep(10)  # first check after 10s
        while not self._stop_event.is_set():
            await log_sink_levels()
            await asyncio.sleep(15)

    # ── Emit helpers ──────────────────────────────────────────────────────────

    async def _emit_transcript(
        self, text: str, speaker: str, source: str, role: str
    ):
        await self.on_event(TranscriptEvent(
            session_id=self.session_id,
            speaker=speaker,
            text=text,
            source=source,
            role=role,
            timestamp=datetime.utcnow(),
        ))

    async def _emit_status(self, status: BotStatus, detail: str = ""):
        self.status = status
        await self.on_event(StatusEvent(
            session_id=self.session_id,
            status=status,
            detail=detail,
        ))

    async def _emit_error(self, error: str, tb: str = ""):
        self.status = BotStatus.ERROR
        await self.on_event(ErrorEvent(
            session_id=self.session_id,
            error=error,
            traceback=tb,
        ))

    async def _cleanup(self):
        await self._emit_status(BotStatus.STOPPED)
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass