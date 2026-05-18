import uuid
from typing import List

from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector

from app.models.base import Base, UUIDPrimaryKey, TimestampMixin


class CandidateDocument(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "candidate_documents"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_documents.id"),
        nullable=False,
    )
    text_content: Mapped[str] = mapped_column(Text, nullable=False)

    embedding: Mapped[list | None] = mapped_column(Vector(768), nullable=True)

    document: Mapped["CandidateDocument"] = relationship(
        "CandidateDocument", back_populates="chunks"
    )