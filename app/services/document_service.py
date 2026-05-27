import io
from uuid import UUID

import docx
import pdfplumber
from google import genai
from google.genai import types
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.document import CandidateDocument, DocumentChunk, DocumentStatus
from app.schemas.candidate import CandidateExtraction


class DocumentService:
    @classmethod
    def _client(cls):
        if not getattr(cls, "_client_instance", None):
            cls._client_instance = genai.Client(
                api_key=settings.GEMINI_API_KEY or "dummy_key"
            ).aio
        return cls._client_instance

    EMBEDDING_BATCH_SIZE = 50

    @staticmethod
    async def extract_text(filename: str, content: bytes) -> str:
        """Step 2: Turn uploaded documents into clean text"""
        ext = filename.split(".")[-1].lower()
        text = ""

        try:
            if ext == "txt":
                text = content.decode("utf-8")
            elif ext == "pdf":
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    text = "\n".join([page.extract_text() or "" for page in pdf.pages])
            elif ext == "docx":
                doc = docx.Document(io.BytesIO(content))
                text = "\n".join([para.text for para in doc.paragraphs])
            else:
                raise ValueError(f"Unsupported file format: {ext}")
        except Exception as e:
            raise ValueError(f"Failed to parse document: {str(e)}")

        return text

    @classmethod
    async def extract_candidate_info(cls, text: str) -> CandidateExtraction:
        """Uses Gemini to turn raw resume text into a structured JSON object."""
        prompt = f"""
        Extract the following information from the resume text provided below.
        If a field is not found, return null. 
        Return the data in valid JSON format.

        Resume Text:
        {text}
        """

        # We use the 'generate_content' with a response_mime_type constraint
        response = await cls._client().models.generate_content(
            model="gemini-flash-lite-latest",  # Use Flash for low latency extraction
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CandidateExtraction,
            ),
        )

        return CandidateExtraction.model_validate_json(response.text)

    @staticmethod
    def chunk_text(text: str) -> list[str]:
        """Step 3: Split into smaller searchable sections"""
        # Recursive splitter tries to split by paragraph, then sentence, then word.
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,  # characters per chunk
            chunk_overlap=150,  # overlap so context isn't lost across boundaries
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_text(text)

        return [f"retrieval_document:\n{chunk}" for chunk in chunks]

    @classmethod
    async def get_embedding_batch(
        cls,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = await cls._client().models.embed_content(
                model="gemini-embedding-001",
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768,
                ),
            )

            return [embedding.values for embedding in response.embeddings]

        except Exception as e:
            raise RuntimeError(f"Embedding API call failed: {str(e)}")

    @classmethod
    async def get_embedding(cls, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for i in range(0, len(texts), cls.EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + cls.EMBEDDING_BATCH_SIZE]

            batch_embeddings = await cls.get_embedding_batch(batch)

            if len(batch_embeddings) != len(batch):
                raise RuntimeError("Embedding batch size mismatch")

            embeddings.extend(batch_embeddings)

        return embeddings

    @classmethod
    async def process_document(
        cls,
        document_id: UUID,
        filename: str,
        content: bytes,
        db: AsyncSession | None = None,  # ← tests inject their session here
    ) -> None:
        async def _run(db: AsyncSession) -> None:
            try:
                result = await db.execute(
                    select(CandidateDocument).where(CandidateDocument.id == document_id)
                )
                document = result.scalar_one()

                document.status = DocumentStatus.PROCESSING
                document.error_message = None
                await db.commit()

                raw_text = await cls.extract_text(filename, content)

                if not raw_text or not raw_text.strip():
                    document.status = DocumentStatus.FAILED
                    document.error_message = "Document contains no readable text"
                    await db.commit()
                    return

                chunks = cls.chunk_text(raw_text)
                embeddings = await cls.get_embedding(chunks)

                chunk_records = [
                    DocumentChunk(
                        document_id=document_id,
                        text_content=text,
                        embedding=embedding,
                    )
                    for text, embedding in zip(chunks, embeddings)
                ]

                db.add_all(chunk_records)
                document.status = DocumentStatus.COMPLETED
                document.error_message = None
                await db.commit()

            except Exception as e:
                await db.rollback()

                result = await db.execute(
                    select(CandidateDocument).where(CandidateDocument.id == document_id)
                )
                document = result.scalar_one_or_none()

                if document:
                    document.status = DocumentStatus.FAILED
                    document.error_message = str(e)
                    await db.commit()

        if db is not None:
            # Caller (test) owns the session — use it directly
            await _run(db)
        else:
            # Production path — manage our own session
            async with AsyncSessionLocal() as db:
                await _run(db)
