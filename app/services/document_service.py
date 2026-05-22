import io

import docx
import pdfplumber
from google import genai
from google.genai import types
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


class DocumentService:
    _client = genai.Client(api_key=settings.GEMINI_API_KEY).aio

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
    async def get_embedding(cls, texts: list[str]) -> list[list[float]]:
        """Step 4: Convert text chunks into cloud-generated vector embeddings"""
        if not texts:
            return []

        try:
            response = await cls._client.models.embed_content(
                model="gemini-embedding-001",
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768,  # Truncates to match DB column width
                ),
            )

            return [embedding.values for embedding in response.embeddings]

        except Exception as e:
            raise RuntimeError(f"Embedding API call failed: {str(e)}")
