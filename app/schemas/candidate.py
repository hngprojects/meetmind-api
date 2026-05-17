# app/schemas/candidate.py
"""
Pydantic schemas for candidate search and export.

Why a separate schema file?
Each domain in this codebase has its own schema file — auth.py, interview.py,
verification.py. Following that pattern keeps things predictable and avoids
circular imports between models and routes.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class CandidateSearchResult(BaseModel):
    """
    Represents a single candidate in the search results list.

    We expose only the fields useful for a search result card —
    not the full candidate record with all URLs. This follows the
    principle of minimal data exposure: don't send what the client
    doesn't need.

    Why not use the full Candidate model directly?
    SQLAlchemy models are not Pydantic models. We cannot return them
    directly from FastAPI routes. We need a Pydantic schema that mirrors
    the fields we want to expose. This schema is the contract between
    our service and the outside world.
    """

    id: uuid.UUID
    full_name: str
    email: EmailStr | None
    phone: str | None
    avatar_initials: str | None
    resume_url: str | None
    portfolio_url: str | None
    workspace_id: uuid.UUID
    created_at: datetime | None

    model_config = {"from_attributes": True}
    # from_attributes=True tells Pydantic to read data from SQLAlchemy
    # model attributes instead of expecting a dict. Without this,
    # CandidateSearchResult.model_validate(candidate_orm_object) would fail.


class CandidateProfile(BaseModel):
    """
    All fields from the Candidate model.

    Returned by GET /candidates/{id}. No nested stats or interviews — just
    the raw candidate record serialized via model_validate.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    avatar_initials: str | None
    resume_url: str | None
    portfolio_url: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}
