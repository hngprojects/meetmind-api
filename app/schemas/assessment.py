from typing import Union

from pydantic import BaseModel


class AssessmentEvidence(BaseModel):
    question_turn_id: Union[int, str]
    response_turn_id: Union[int, str]
    reason: str


class AssessmentSubRubric(BaseModel):
    id: str
    title: str
    score: int  # 0-100
    confidence: int = 0  # 0-100
    justification: str = ""
    strengths: list[str] = []
    weaknesses: list[str] = []
    evidence: list[AssessmentEvidence] = []


class AssessmentCriterionScore(BaseModel):
    id: str
    title: str
    score: int  # 0-100
    confidence: int = 0  # 0-100
    justification: str = ""
    signals_detected: list[str]
    strengths: list[str] = []
    weaknesses: list[str] = []
    questions_asked: list[str] = []
    sub_rubrics: list[AssessmentSubRubric] = []
    evidence: list[AssessmentEvidence] = []


class AssessmentOutput(BaseModel):
    observation: str
    criteria: list[AssessmentCriterionScore] = []
    highlights: list[str]
    red_flags: list[str]
