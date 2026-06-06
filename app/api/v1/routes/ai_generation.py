"""Routes to trigger AI generation for interviews."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import APIError, APIResponse, success
from app.core.utils import safe_notify
from app.db.session import get_session
from app.schemas.ai_generation import (
    ChatAnswerData,
    CompleteInterviewData,
    GeneratedQuestionResponse,
    RecordedResponseData,
    SummaryGeneratingData,
    SummaryRetryData,
)
from app.schemas.chat import (
    AskRequest,
    ChatDocumentUploadResponse,
    ChatHistoryResponse,
    ChatVoiceUploadResponse,
    RespondRequest,
)
from app.services.ai_generation_service import AIGenerationService
from app.services.interview import InterviewService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/{interview_id}/generate-question",
    response_model=APIResponse[GeneratedQuestionResponse],
)
async def generate_question(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    question = await AIGenerationService.generate_next_question(
        interview_id=interview_id,
        db=db,
        user=user,
    )
    return success(
        {"question": question},
        message="Question generated",
        status_code=status.HTTP_200_OK,
    )


@router.post(
    "/{interview_id}/respond", response_model=APIResponse[RecordedResponseData]
)
async def respond_to_question(
    interview_id: uuid.UUID,
    payload: RespondRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    next_question = await AIGenerationService.record_response(
        interview_id=interview_id,
        content=payload.content,
        user=user,
        db=db,
    )
    return success({"response": next_question}, message="Response recorded")


@router.post(
    "/{interview_id}/complete", response_model=APIResponse[CompleteInterviewData]
)
async def complete_interview(
    interview_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    interview = await AIGenerationService.get_interview_for_user(interview_id, user, db)
    await AIGenerationService.complete_interview(
        interview_id=interview_id,
        user=user,
        db=db,
    )
    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
    )

    await safe_notify(
        db,
        user_id=user.id,
        type="report",
        title="Interview Completed",
        description=interview.role_title or "Interview",
        action_url=f"/interviews/{interview_id}",
        label="completion notification",
    )

    return success(
        {"status": "completed"},
        message="Interview completed, assessment generation started",
    )


@router.post("/{interview_id}/chat", response_model=APIResponse[ChatAnswerData])
async def ask_question(
    interview_id: uuid.UUID,
    payload: AskRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await AIGenerationService.send_chat_message(
        interview_id=interview_id,
        content=payload.query,
        user=user,
        db=db,
    )
    return success(result, message="Query answered")


@router.get("/{interview_id}/chat", response_model=APIResponse[ChatHistoryResponse])
async def get_chat_history(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve the full chat history for an interview session."""
    from app.services.chat_history import ChatHistoryService

    history = await ChatHistoryService.get_chat_history(interview_id, db, user)
    return success(
        history.model_dump(mode="json"),
        message="Chat history retrieved successfully",
    )


MAX_AUDIO_FILE_SIZE = 25 * 1024 * 1024
MAX_DOCUMENT_FILE_SIZE = 10 * 1024 * 1024

SUPPORTED_AUDIO_FORMATS = {
    "audio/webm",
    "audio/wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/flac",
    "audio/x-m4a",
    "audio/x-wav",
}
SUPPORTED_DOCUMENT_FORMATS = {".pdf", ".docx", ".txt"}


@router.post(
    "/{interview_id}/chat/voice",
    response_model=APIResponse[ChatVoiceUploadResponse],
)
async def ask_question_voice(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    file: UploadFile = File(..., description="Audio file"),
):
    if file.content_type not in SUPPORTED_AUDIO_FORMATS:
        raise APIError(
            f"Unsupported audio format: {file.content_type}",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_audio_format",
        )
    content = await file.read()
    if len(content) > MAX_AUDIO_FILE_SIZE:
        raise APIError(
            "Audio file too large (max 25 MB)",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="file_too_large",
        )
    result = await AIGenerationService.send_chat_voice(
        interview_id=interview_id,
        audio_content=content,
        filename=file.filename or "audio.webm",
        user=user,
        db=db,
    )
    return success(result, message="Voice query answered")


@router.post(
    "/{interview_id}/chat/document",
    response_model=APIResponse[ChatDocumentUploadResponse],
)
async def ask_question_document(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    file: UploadFile = File(..., description="Document file (PDF, DOCX, TXT)"),
):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in SUPPORTED_DOCUMENT_FORMATS:
        raise APIError(
            f"Unsupported document format: {ext}",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_document_format",
        )
    content = await file.read()
    if len(content) > MAX_DOCUMENT_FILE_SIZE:
        raise APIError(
            "Document file too large (max 10 MB)",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="file_too_large",
        )
    try:
        result = await AIGenerationService.send_chat_document(
            interview_id=interview_id,
            file_content=content,
            filename=file.filename or "document.txt",
            user=user,
            db=db,
        )
    except ValueError as e:
        raise APIError(
            str(e), status_code=status.HTTP_400_BAD_REQUEST, code="invalid_file"
        )
    return success(result, message="Document query answered")


@router.post(
    "/{interview_id}/summary/retry", response_model=APIResponse[SummaryRetryData]
)
async def retry_interview_summary(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.retry_summary(interview_id, db, user)
    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
    )

    interview = await AIGenerationService.get_interview_for_user(interview_id, user, db)
    await safe_notify(
        db,
        user_id=user.id,
        type="report",
        title="Summary Regeneration Started",
        description=interview.role_title or "Interview",
        action_url=f"/interviews/{interview_id}",
        label="retry notification",
    )

    return success(result, message="Summary retry started")


@router.post(
    "/{interview_id}/summary/generate",
    status_code=202,
    response_model=APIResponse[SummaryGeneratingData],
)
async def generate_interview_summary(
    interview_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    interview = await AIGenerationService.get_interview_for_user(interview_id, user, db)

    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
    )

    await safe_notify(
        db,
        user_id=user.id,
        type="report",
        title="Summary Generation Started",
        description=interview.role_title or "Interview",
        action_url=f"/interviews/{interview_id}",
        label="generation notification",
    )

    return success(
        {"status": "generating"},
        message="Assessment generation started",
        status_code=status.HTTP_202_ACCEPTED,
    )
