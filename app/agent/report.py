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

Score the CANDIDATE only. For each rubric criterion:
1. Provide a "percentage" score (0-100) based on their answers.
2. List the specific "questions" asked (by the interviewer) relating to this criterion.
3. List 2-4 key "signals" (competencies/traits) detected from their answer.
4. Provide one sentence of "justification" grounded in the transcript.

Then give an overall weighted recommendation: one of strong_yes, yes, no, strong_no.

Also generate:
- "summary": a concise, objective recruiter recap of the candidate's professional
  background, skills, and overall interview performance. Strip conversational
  fluff and use only evidence from the transcript.
- "highlights": standout positive moments, exceptional alignment, clear STAR-style
  answers, or major achievements evidenced in the transcript. Return [] if none.
- "red_flags": warning signs only from these categories: vague/evasive
  communication, unexplained job hopping, poor professional conduct, lack of
  genuine interest, unwarranted overconfidence/discrepancies, or defensiveness
  regarding background verification. Return [] if none.
- "confidence": a number from 0 to 1 reflecting how reliable this assessment is
  given transcript completeness and quality. If the transcript appears degraded
  by accent, background noise, microphone issues, missing context, or ambiguous
  wording, still score it but lower this confidence.

Rubric:
{rubric_block}

Transcript:
{convo}

Respond with ONLY JSON, no prose or markdown fences:
{{
  "criteria": [
    {{
      "name": "...",
      "percentage": 0,
      "questions": ["...", "..."],
      "signals": ["...", "..."],
      "justification": "..."
    }}
  ],
  "overall": "...",
  "summary": "...",
  "highlights": ["...", "..."],
  "red_flags": ["...", "..."],
  "confidence": 0.0
}}"""

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
