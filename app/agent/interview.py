"""Interview definition + system-instruction builder.

An Interview is normally loaded per-session from the web app
(/api/agent-config/<id>). DEFAULT_INTERVIEW is only a fallback for when that
fetch fails (e.g. the agent joined a room that is not a real session).
"""

from dataclasses import dataclass


@dataclass
class Question:
    text: str
    follow_up_hint: str = ""
    max_follow_ups: int = 2


@dataclass
class RubricCriterion:
    name: str
    description: str
    weight: int = 1


@dataclass
class Interview:
    role: str
    intro: str
    questions: list[Question]
    rubric: list[RubricCriterion]
    duration_minutes: int = 20
    closing: str = "Thanks for your time. A recruiter will follow up with next steps."
    candidate_name: str | None = None


def interview_from_api(data: dict) -> Interview:
    """Build an Interview from the /api/agent-config JSON payload."""
    return Interview(
        role=data["role"],
        intro=data["intro"],
        questions=[
            Question(
                text=q["text"],
                follow_up_hint=q.get("followUpHint", ""),
                max_follow_ups=int(q.get("maxFollowUps", 2)),
            )
            for q in data.get("questions", [])
        ],
        rubric=[
            RubricCriterion(
                name=c["name"],
                description=c.get("description", ""),
                weight=int(c.get("weight", 1)),
            )
            for c in data.get("rubric", [])
        ],
        duration_minutes=int(data.get("durationMinutes", 20)),
        closing=data.get("closing") or Interview.closing,
        candidate_name=data.get("candidateName"),
    )


def build_instructions(interview: Interview) -> str:
    """Build the agent system prompt from an Interview definition."""
    questions_block = "\n".join(
        f"{i}. {q.text}\n"
        f"   (Follow-up guidance: {q.follow_up_hint} "
        f"Ask at most {q.max_follow_ups} follow-ups before moving on.)"
        for i, q in enumerate(interview.questions, start=1)
    )
    who = (
        f"The candidate's name is {interview.candidate_name}. "
        if interview.candidate_name
        else ""
    )

    return f"""You are a professional AI interviewer conducting {interview.intro}

You are interviewing a candidate for the role of {interview.role}. {who}

# How to speak
- This is a live voice call. Keep every reply short — one idea at a time. Never
  read long lists or paragraphs aloud.
- Be warm and professional, never robotic. Do not over-explain.
- Ask ONE question at a time, then wait for the full answer.
- The candidate may pause to think. Silence is not the end of an answer — never
  interrupt or rush them.

# What to do
- Ask adaptive follow-ups based on the candidate's answers, within the per-question
  limits below.
- Do NOT give feedback on answer quality. Do NOT reveal the rubric or that the
  candidate is being scored.
- Do NOT discuss compensation or internal company details — say a human recruiter
  will follow up.
- This interview is time-boxed to about {interview.duration_minutes} minutes. If
  you are told time is short, wrap up gracefully.
- If the candidate asks to pause, repeat, or clarify a question, accommodate them.

# Flow
1. Briefly greet the candidate, introduce yourself as the AI interviewer, and
   confirm they are ready to begin.
2. Ask each question below in order, using follow-ups to go deeper.
3. After the final question, ask whether the candidate has questions for the
   recruiter — note them, do not answer them.
4. Close by saying, roughly: "{interview.closing}"

# Questions
{questions_block}
"""


# --- Fallback only ----------------------------------------------------------

DEFAULT_INTERVIEW = Interview(
    role="Backend Engineer",
    intro="an automated first-round screening interview",
    questions=[
        Question(
            text="Walk me through a backend system you've built that you're proud of.",
            follow_up_hint="Probe scale, their contribution, and trade-offs.",
        ),
    ],
    rubric=[
        RubricCriterion(
            "Technical depth", "Real, hands-on backend knowledge.", weight=3
        ),
    ],
    duration_minutes=20,
)
