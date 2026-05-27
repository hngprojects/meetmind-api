from pydantic import BaseModel


class AssessmentOutput(BaseModel):
    observation: str
    highlights: list[str]
    red_flags: list[str]
