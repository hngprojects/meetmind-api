from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from google.genai import types

from app.models.document import DocumentChunk, CandidateDocument
from app.services.document_service import DocumentService


class InterviewContextService:

    @staticmethod
    async def retrieve_relevant_chunks(
        candidate_id: UUID,
        query: str,
        db: AsyncSession,
        limit: int = 5
    ) -> list[str]:
        try:
            query_response = await DocumentService._client.models.embed_content(
                model="gemini-embedding-001",
                contents=query,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=768
                )
            )
            
            query_vector = query_response.embeddings[0].values

        except Exception as e:
            raise RuntimeError(f"Failed to generate query embedding: {str(e)}")

        stmt = (
            select(DocumentChunk.text_content)
            .join(CandidateDocument)
            .where(CandidateDocument.candidate_id == candidate_id)
            .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]


    @staticmethod
    async def build_session_context(
        candidate_id: UUID, 
        job_description: str, 
        scorecard: str, 
        db: AsyncSession
    ) -> str:
        
        search_query = f"Candidate experience, skills, and background relevant to: {job_description}"
        retrieved_texts = await InterviewContextService.retrieve_relevant_chunks(
            candidate_id=candidate_id, 
            query=search_query, 
            db=db
        )
        
        formatted_resume_context = "\n---\n".join(retrieved_texts)

        system_prompt = f"""
        You are MeetMind, an expert Technical Recruiter conducting an interview. 
        You are speaking to the candidate via a live audio call. Keep your responses conversational, concise, and natural. Do not speak in bullet points.

        # JOB DESCRIPTION
        {job_description}

        # EVALUATION SCORECARD
        {scorecard}

        # CANDIDATE CONTEXT (From Uploaded Resume/Docs)
        {formatted_resume_context}

        # INSTRUCTIONS
        Based on the candidate's background and the scorecard, formulate your next interview question. Do not repeat questions you have already asked. 
        """
        
        return system_prompt