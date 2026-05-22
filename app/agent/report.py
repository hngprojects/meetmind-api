"""Generate the post-interview AI report from the transcript.

Uses LiveKit Inference for the LLM call — billed through the LiveKit account,
no separate provider key.
"""

import json
import logging

from livekit.agents import inference, llm

from app.agent.interview import Interview

logger = logging.getLogger("interviewer.report")


async def generate_report(
    turns: list[dict], interview: Interview, llm_model: str
) -> dict | None:
    """Score the candidate against the rubric. Returns the report dict, or None
    if there is nothing to score."""
    if not turns:
        return None

    convo = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
    rubric_block = "\n".join(
        f"- {c.name} (weight {c.weight}): {c.description}" for c in interview.rubric
    )

    prompt = f"""You are evaluating a job interview transcript for the role of \
{interview.role}.

Score the CANDIDATE only. For each rubric criterion, give an integer 1-5 score
and one sentence of justification grounded in the transcript. Then give an
overall weighted recommendation: one of strong_yes, yes, no, strong_no.

Rubric:
{rubric_block}

Transcript:
{convo}

Respond with ONLY JSON, no prose or markdown fences:
{{"criteria": [{{"name": "...", "score": 0, "justification": "..."}}],
  "overall": "...", "summary": "..."}}"""

    ctx = llm.ChatContext.empty()
    ctx.add_message(role="user", content=prompt)

    text = ""
    async for chunk in (
        inference.LLM(model=llm_model).chat(chat_ctx=ctx).to_str_iterable()
    ):
        text += chunk

    return _parse_json(text)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return json.loads(text)
