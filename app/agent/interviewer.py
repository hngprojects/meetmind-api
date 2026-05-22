"""LiveKit AI interviewer agent.

Run locally:  python interviewer.py dev

On join the agent's room name is the interview session id. It loads that
session's config from the web app, runs a time-boxed interview, then posts the
transcript + AI report back.
"""

import asyncio
import logging
import os

import aiohttp
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    inference,
)
from livekit.plugins import silero

from app.agent.interview import (
    DEFAULT_INTERVIEW,
    Interview,
    build_instructions,
    interview_from_api,
)
from app.agent.report import generate_report
from app.agent.transcript import extract_turns, save_transcript

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interviewer")

# LiveKit Inference model IDs — billed through the LiveKit account.
STT_MODEL = os.getenv("INTERVIEWER_STT", "deepgram/nova-3")
LLM_MODEL = os.getenv("INTERVIEWER_LLM", "openai/gpt-5.2-chat-latest")
TTS_MODEL = os.getenv("INTERVIEWER_TTS", "cartesia/sonic-3")
TTS_VOICE = os.getenv("INTERVIEWER_TTS_VOICE", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc")
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost:8000")

WARN_BEFORE_END_SEC = 120

server = AgentServer()


class Interviewer(Agent):
    def __init__(self, interview: Interview):
        super().__init__(instructions=build_instructions(interview))


async def load_interview(session_id: str) -> Interview:
    """Fetch the interview config for this room from the web app."""
    url = f"{WEB_BASE_URL}/api/v1/livekit/{session_id}/config"
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return interview_from_api(await r.json())
                logger.warning("agent-config %s returned %s", session_id, r.status)
    except Exception:
        logger.exception("failed to fetch interview config")
    logger.info("using DEFAULT_INTERVIEW fallback")
    return DEFAULT_INTERVIEW


async def post_result(session_id: str, turns: list[dict], report: dict | None) -> None:
    """Send transcript + report back to the web app."""
    url = f"{WEB_BASE_URL}/api/v1/livekit/{session_id}/result"
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                url,
                json={"transcript": turns, "report": report},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                logger.info("posted result for %s -> HTTP %s", session_id, r.status)
    except Exception:
        logger.exception("failed to post result")


async def run_timer(
    ctx: agents.JobContext, session: AgentSession, interview: Interview
):
    """End the interview at the time limit, warning ~2 minutes before."""
    total = interview.duration_minutes * 60
    warn_at = max(total - WARN_BEFORE_END_SEC, 0)
    try:
        await asyncio.sleep(warn_at)
        if total > WARN_BEFORE_END_SEC:
            session.generate_reply(
                instructions="About two minutes remain. Let the candidate finish "
                "their current thought, then start wrapping up."
            )
        await asyncio.sleep(total - warn_at)
        await session.generate_reply(
            instructions="The interview time is up. Thank the candidate warmly, "
            f"then close with, roughly: {interview.closing}"
        )
    except asyncio.CancelledError:
        return
    # End the call for everyone — deleting the room disconnects all participants.
    try:
        await ctx.delete_room()
    except Exception:
        logger.exception("failed to close room")
    ctx.shutdown(reason="interview time limit reached")


@server.rtc_session()
async def interview_session(ctx: agents.JobContext):
    session_id = ctx.room.name
    interview = await load_interview(session_id)
    logger.info("interview for session %s — role: %s", session_id, interview.role)

    session = AgentSession(
        stt=inference.STT(model=STT_MODEL, language="multi"),
        llm=inference.LLM(model=LLM_MODEL),
        tts=inference.TTS(model=TTS_MODEL, voice=TTS_VOICE),
        vad=silero.VAD.load(),
        # turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
    )

    async def on_shutdown():
        turns = extract_turns(session.history)
        try:
            save_transcript(session_id, turns)
        except Exception:
            logger.exception("failed to save local transcript")
        report = None
        try:
            report = await generate_report(turns, interview, LLM_MODEL)
        except Exception:
            logger.exception("failed to generate report")
        await post_result(session_id, turns, report)

    ctx.add_shutdown_callback(on_shutdown)

    await session.start(room=ctx.room, agent=Interviewer(interview))
    await session.generate_reply(
        instructions="Greet the candidate, introduce yourself as the AI "
        "interviewer, and ask if they are ready to begin."
    )

    asyncio.create_task(run_timer(ctx, session, interview))


if __name__ == "__main__":
    agents.cli.run_app(server)
