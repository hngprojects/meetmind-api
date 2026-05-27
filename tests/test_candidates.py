# tests/test_candidates.py
"""
Tests for candidate search and export endpoints.

Test naming follows the repo convention:
test_<action>_<expected_outcome>_<condition>
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.document import CandidateDocument, DocumentChunk, DocumentStatus
from app.models.interview import Candidate
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.document_service import DocumentService

SEARCH_URL = "/api/v1/candidates/search"
EXPORT_URL = "/api/v1/candidates/export"
GET_CANDIDATE_URL = "/api/v1/candidates"


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def create_user_with_workspace(db_session) -> tuple[User, Workspace]:
    """Create a user and a workspace, link them as owner."""
    user = User(
        name="Test User",
        email=f"test-{uuid.uuid4()}@example.com",
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(
        name="Test Workspace",
        created_by=user.id,
    )
    db_session.add(workspace)
    await db_session.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
    )
    db_session.add(member)
    await db_session.commit()

    return user, workspace


async def create_candidate(db_session, workspace_id, full_name, email=None):
    """Create a test candidate in a workspace."""
    candidate = Candidate(
        workspace_id=workspace_id,
        full_name=full_name,
        email=email,
    )
    db_session.add(candidate)
    await db_session.commit()
    return candidate


def auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# ─── Search Tests ──────────────────────────────────────────────────────────────


class TestCandidateSearch:
    @pytest.mark.anyio
    async def test_search_returns_200_with_valid_query(self, client, db_session):
        """
        A valid search query from an authenticated user returns 200.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            SEARCH_URL,
            params={"q": "john"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body

    @pytest.mark.anyio
    async def test_search_returns_401_without_token(self, client):
        """
        An unauthenticated request to search returns 401.
        """
        response = await client.get(SEARCH_URL, params={"q": "john"})
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_search_returns_422_without_query_param(self, client, db_session):
        """
        A search request missing the q parameter returns 422.
        The q parameter is required (Query(...) with min_length=1).
        """
        from app.services.auth import AuthService

        user, _ = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            SEARCH_URL,
            headers=auth_header(token),
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_search_returns_matching_candidates_by_name(self, client, db_session):
        """
        Searching by name returns candidates whose full_name matches the query.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        await create_candidate(db_session, workspace.id, "John Okafor", "john@test.com")
        await create_candidate(db_session, workspace.id, "Jane Doe", "jane@test.com")

        response = await client.get(
            SEARCH_URL,
            params={"q": "John"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        names = [c["full_name"] for c in data]
        assert "John Okafor" in names
        assert "Jane Doe" not in names

    @pytest.mark.anyio
    async def test_search_is_case_insensitive(self, client, db_session):
        """
        Search for 'john' should match 'John', 'JOHN', 'john' — ilike handles this.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        await create_candidate(db_session, workspace.id, "JOHN UPPERCASE")
        await create_candidate(db_session, workspace.id, "john lowercase")

        response = await client.get(
            SEARCH_URL,
            params={"q": "john"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        names = [c["full_name"] for c in data]
        assert "JOHN UPPERCASE" in names
        assert "john lowercase" in names

    @pytest.mark.anyio
    async def test_search_returns_empty_list_when_no_match(self, client, db_session):
        """
        A search that matches nothing returns an empty list, not an error.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            SEARCH_URL,
            params={"q": "zxqwerty12345notaname"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.anyio
    async def test_search_pagination_meta_is_present(self, client, db_session):
        """
        Response includes pagination metadata: page, page_size, total, total_pages.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            SEARCH_URL,
            params={"q": "a", "page": 1, "page_size": 10},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        meta = response.json()["meta"]["pagination"]
        assert "page" in meta
        assert "page_size" in meta
        assert "total" in meta
        assert "total_pages" in meta


# ─── Export Tests ──────────────────────────────────────────────────────────────


class TestCandidateExport:
    @pytest.mark.anyio
    async def test_export_returns_200_with_csv_content_type(self, client, db_session):
        """
        Export returns 200 with Content-Type: text/csv.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            EXPORT_URL,
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    @pytest.mark.anyio
    async def test_export_returns_401_without_token(self, client):
        """
        Unauthenticated export request returns 401.
        """
        response = await client.get(EXPORT_URL)
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_export_response_has_content_disposition_header(
        self, client, db_session
    ):
        """
        Export response includes Content-Disposition attachment header.
        This is what tells the browser to download the file.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            EXPORT_URL,
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert "attachment" in response.headers.get("content-disposition", "")
        assert "candidates_" in response.headers.get("content-disposition", "")

    @pytest.mark.anyio
    async def test_export_csv_contains_header_row(self, client, db_session):
        """
        The first line of the CSV is the column header row.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            EXPORT_URL,
            headers=auth_header(token),
        )

        assert response.status_code == 200
        first_line = response.text.split("\n")[0]
        assert "full_name" in first_line
        assert "email" in first_line


# ─── Get Single Candidate Tests ────────────────────────────────────────────────


class TestCandidateGetByID:
    @pytest.mark.anyio
    async def test_get_returns_200_with_candidate_data(self, client, db_session):
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        candidate = await create_candidate(
            db_session, workspace.id, "Alice Wonder", "alice@test.com"
        )

        response = await client.get(
            f"{GET_CANDIDATE_URL}/{candidate.id}",
            headers=auth_header(token),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["message"] == "Candidate profile retrieved"
        data = body["data"]
        assert data["id"] == str(candidate.id)
        assert data["name"] == "Alice Wonder"
        assert data["email"] == "alice@test.com"
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.anyio
    async def test_get_returns_401_without_token(self, client):
        candidate_id = uuid.uuid4()
        response = await client.get(f"{GET_CANDIDATE_URL}/{candidate_id}")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_get_returns_422_for_invalid_uuid(self, client, db_session):
        from app.services.auth import AuthService

        user, _ = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            f"{GET_CANDIDATE_URL}/not-a-uuid",
            headers=auth_header(token),
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_get_returns_404_for_no_workspace(self, client, db_session):
        from app.services.auth import AuthService

        user = User(
            name="Lonely User",
            email=f"lonely-{uuid.uuid4()}@example.com",
            is_verified=True,
        )
        db_session.add(user)
        await db_session.commit()
        token = await AuthService.create_access_token(user)

        candidate_id = uuid.uuid4()
        response = await client.get(
            f"{GET_CANDIDATE_URL}/{candidate_id}",
            headers=auth_header(token),
        )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "no_workspace_found"

    @pytest.mark.anyio
    async def test_get_returns_404_for_nonexistent_id(self, client, db_session):
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        missing_id = uuid.uuid4()

        response = await client.get(
            f"{GET_CANDIDATE_URL}/{missing_id}",
            headers=auth_header(token),
        )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "candidate_not_found"

    @pytest.mark.anyio
    async def test_get_returns_404_for_cross_workspace_access(self, client, db_session):
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        candidate = await create_candidate(
            db_session, workspace.id, "Visible", "visible@test.com"
        )

        other_user = User(
            name="Other User",
            email=f"other-{uuid.uuid4()}@example.com",
            is_verified=True,
        )
        db_session.add(other_user)
        await db_session.flush()
        other_workspace = Workspace(name="Other Workspace", created_by=other_user.id)
        db_session.add(other_workspace)
        await db_session.flush()
        other_member = WorkspaceMember(
            workspace_id=other_workspace.id, user_id=other_user.id, role="owner"
        )
        db_session.add(other_member)
        await db_session.commit()
        other_token = await AuthService.create_access_token(other_user)

        response = await client.get(
            f"{GET_CANDIDATE_URL}/{candidate.id}",
            headers=auth_header(other_token),
        )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "candidate_not_found"


class TestCandidateDocumentUpload:
    @pytest.mark.anyio
    @patch("app.services.document_service.DocumentService.process_document")
    async def test_upload_document_returns_200_and_schedules_task(
        self,
        mock_process_document,
        client,
        db_session,
    ):
        """
        Upload creates document record and schedules background processing.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        candidate = await create_candidate(
            db_session,
            workspace.id,
            "Resume Owner",
            "owner@test.com",
        )

        file_content = b"This is a valid document used for testing."
        files = {"file": ("resume.txt", file_content, "text/plain")}

        response = await client.post(
            f"{GET_CANDIDATE_URL}/{candidate.id}/documents/upload",
            files=files,
            headers=auth_header(token),
        )

        assert response.status_code == 200
        body = response.json()

        assert body["success"] is True
        assert "Processing" in body["message"]

        # DB verification
        stmt = select(CandidateDocument).where(
            CandidateDocument.candidate_id == candidate.id
        )
        result = await db_session.execute(stmt)
        doc = result.scalar_one_or_none()

        assert doc is not None
        assert doc.filename == "resume.txt"
        assert doc.status == DocumentStatus.PENDING

        # background task was scheduled
        mock_process_document.assert_called_once()

    @pytest.mark.anyio
    async def test_upload_requires_auth(self, client):
        """
        Unauthorized upload is rejected.
        """
        candidate_id = uuid.uuid4()
        files = {"file": ("resume.txt", b"text", "text/plain")}

        response = await client.post(
            f"{GET_CANDIDATE_URL}/{candidate_id}/documents/upload",
            files=files,
        )

        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_upload_rejects_oversized_file(
        self,
        client,
        db_session,
    ):
        """
        File size validation prevents large uploads.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        candidate = await create_candidate(
            db_session,
            workspace.id,
            "Size Test",
            "size@test.com",
        )

        files = {"file": ("resume.txt", b"x" * (20 * 1024 * 1024), "text/plain")}

        response = await client.post(
            f"{GET_CANDIDATE_URL}/{candidate.id}/documents/upload",
            files=files,
            headers=auth_header(token),
        )

        assert response.status_code == 413

    @pytest.mark.anyio
    async def test_upload_returns_500_on_db_failure(
        self,
        client,
        db_session,
    ):
        """
        DB failures during document creation return 500.
        """
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        candidate = await create_candidate(
            db_session,
            workspace.id,
            "Fail Test",
            "fail@test.com",
        )

        db_session.commit = AsyncMock(side_effect=Exception("DB failure"))

        files = {"file": ("resume.txt", b"text", "text/plain")}

        response = await client.post(
            f"{GET_CANDIDATE_URL}/{candidate.id}/documents/upload",
            files=files,
            headers=auth_header(token),
        )

        assert response.status_code == 500
        assert "Database insertion failed" in response.text


class TestDocumentProcessing:
    @pytest.mark.anyio
    @patch("app.services.document_service.DocumentService.get_embedding")
    async def test_successful_document_processing(self, mock_embed, db_session):
        mock_embed.return_value = [[0.1] * 768]

        doc = CandidateDocument(
            candidate_id=uuid.uuid4(),
            filename="test.txt",
            status=DocumentStatus.PENDING,
        )

        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        await DocumentService.process_document(
            document_id=doc.id,
            filename="test.txt",
            content=b"valid content for processing",
            db=db_session,
        )

        await db_session.refresh(doc)

        assert doc.status == DocumentStatus.COMPLETED

        chunks = (
            (
                await db_session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
                )
            )
            .scalars()
            .all()
        )

        assert len(chunks) > 0

    @pytest.mark.anyio
    @patch("app.services.document_service.DocumentService.get_embedding")
    async def test_empty_document_marks_failed(self, mock_embed, db_session):
        doc = CandidateDocument(
            candidate_id=uuid.uuid4(),
            filename="empty.txt",
            status=DocumentStatus.PENDING,
        )

        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        await DocumentService.process_document(
            document_id=doc.id,
            filename="empty.txt",
            content=b"   ",
            db=db_session,
        )

        await db_session.refresh(doc)

        assert doc.status == DocumentStatus.FAILED
        assert doc.error_message is not None

    @pytest.mark.anyio
    @patch("app.services.document_service.DocumentService.get_embedding")
    async def test_embedding_failure_marks_document_failed(
        self, mock_embed, db_session
    ):
        mock_embed.side_effect = Exception("embedding failed")

        doc = CandidateDocument(
            candidate_id=uuid.uuid4(),
            filename="test.txt",
            status=DocumentStatus.PENDING,
        )

        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        await DocumentService.process_document(
            document_id=doc.id,
            filename="test.txt",
            content=b"valid text content",
            db=db_session,
        )

        await db_session.refresh(doc)

        assert doc.status == DocumentStatus.FAILED

    @pytest.mark.anyio
    async def test_unsupported_file_type_fails(self, db_session):
        doc = CandidateDocument(
            candidate_id=uuid.uuid4(),
            filename="file.xyz",
            status=DocumentStatus.PENDING,
        )

        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        await DocumentService.process_document(
            document_id=doc.id,
            filename="file.xyz",
            content=b"data",
            db=db_session,
        )

        await db_session.refresh(doc)

        assert doc.status == DocumentStatus.FAILED


class TestListCandidates:
    @pytest.mark.anyio
    async def test_list_candidates_returns_200_with_valid_request(
        self, client, db_session
    ):
        from app.services.auth import AuthService

        user, _ = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            "/api/v1/candidates",
            headers=auth_header(token),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert "pagination" in body["meta"]

    @pytest.mark.anyio
    async def test_list_candidates_filters_by_status(self, client, db_session):
        from app.services.auth import AuthService
        from app.models.interview import Interview

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        candidate = await create_candidate(
            db_session, workspace.id, "Filter Test", "filter@test.com"
        )

        interview = Interview(
            workspace_id=workspace.id,
            candidate_id=candidate.id,
            interviewer_id=user.id,
            status="in_progress",
        )
        db_session.add(interview)
        await db_session.commit()

        response = await client.get(
            "/api/v1/candidates",
            params={"status": "ongoing"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert all(c["status"] == "ongoing" for c in data)

    @pytest.mark.anyio
    async def test_list_candidates_searches_by_name(self, client, db_session):
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        await create_candidate(
            db_session, workspace.id, "Searchable Name", "search@test.com"
        )
        await create_candidate(
            db_session, workspace.id, "Other Person", "other@test.com"
        )

        response = await client.get(
            "/api/v1/candidates",
            params={"q": "Searchable"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1
        assert any("Searchable" in c["name"] for c in data)

    @pytest.mark.anyio
    async def test_list_candidates_returns_empty_when_no_match(
        self, client, db_session
    ):
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            "/api/v1/candidates",
            params={"q": "zxqwerty99notaname"},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.anyio
    async def test_list_candidates_returns_401_without_token(self, client):
        response = await client.get("/api/v1/candidates")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_list_candidates_pagination_meta_is_present(self, client, db_session):
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            "/api/v1/candidates",
            params={"page": 1, "pageSize": 10},
            headers=auth_header(token),
        )

        assert response.status_code == 200
        pagination = response.json()["meta"]["pagination"]
        assert "page" in pagination
        assert "page_size" in pagination
        assert "total" in pagination
        assert "total_pages" in pagination
