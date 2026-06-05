from pydantic import BaseModel


class AssessmentCriterionScore(BaseModel):
    name: str
    score: int  # 0-100
    confidence: int = 0  # 0-100
    justification: str
    signals: list[str]
    strengths: list[str] = []
    weaknesses: list[str] = []
    questions: list[str]


class AssessmentOutput(BaseModel):
    observation: str
    criteria: list[AssessmentCriterionScore]
    highlights: list[str]
    red_flags: list[str]
