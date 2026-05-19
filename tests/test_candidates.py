# tests/test_candidates.py
"""
Tests for candidate search and export endpoints.

Test naming follows the repo convention:
test_<action>_<expected_outcome>_<condition>
"""

import uuid
from unittest.mock import patch

import pytest

from app.models.document import CandidateDocument, DocumentChunk
from app.models.interview import Candidate
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

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
        assert data["full_name"] == "Alice Wonder"
        assert data["email"] == "alice@test.com"
        assert data["workspace_id"] == str(workspace.id)
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
    async def test_upload_document_returns_200_and_completes_background_task(
        self, client, db_session
    ):
        from unittest.mock import AsyncMock, patch

        from sqlalchemy import select

        from app.models.document import DocumentStatus
        from app.services.auth import AuthService
        from app.services.document_service import DocumentService

        user, workspace = await create_user_with_workspace(db_session)
        candidate = await create_candidate(
            db_session, workspace.id, "Candidate", "c@test.com"
        )
        token = await AuthService.create_access_token(user)

        mock_vector = [0.1] * 768

        captured = {}

        def capture_task(func, *args, **kwargs):
            captured["func"] = func
            captured["args"] = args
            captured["kwargs"] = kwargs

        with patch(
            "starlette.background.BackgroundTasks.add_task", side_effect=capture_task
        ):
            file_content = b"This is a test document content for processing."
            files = {"file": ("resume.txt", file_content, "text/plain")}

            response = await client.post(
                f"/api/v1/candidates/{candidate.id}/documents/upload",
                files=files,
                headers=auth_header(token),
            )

        assert response.status_code == 200
        assert "func" in captured, "Background task was never registered"

        # Now run the background task manually, with the embedding mocked
        with patch.object(
            DocumentService,
            "get_embedding",
            new=AsyncMock(return_value=[mock_vector]),
        ):
            await captured["func"](*captured["args"], **captured["kwargs"])

        # Verify final state directly via db_session
        result = await db_session.execute(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == candidate.id
            )
        )
        doc = result.scalar_one_or_none()

        assert doc is not None, "Document record was never created"
        assert doc.status == DocumentStatus.COMPLETED

        result = await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        )
        chunks = result.scalars().all()
        assert len(chunks) > 0
        assert list(chunks[0].embedding) == pytest.approx(mock_vector)

    @pytest.mark.anyio
    async def test_upload_document_handles_empty_text_background_failure(
        self, client, db_session
    ):
        from sqlalchemy import select

        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        candidate = await create_candidate(
            db_session, workspace.id, "Empty", "e@test.com"
        )
        token = await AuthService.create_access_token(user)

        captured = {}

        def capture_task(func, *args, **kwargs):
            captured["func"] = func
            captured["args"] = args
            captured["kwargs"] = kwargs

        with patch(
            "starlette.background.BackgroundTasks.add_task", side_effect=capture_task
        ):
            files = {"file": ("empty.txt", b"   ", "text/plain")}
            response = await client.post(
                f"/api/v1/candidates/{candidate.id}/documents/upload",
                files=files,
                headers=auth_header(token),
            )

        assert response.status_code == 200
        assert "func" in captured, "Background task was never registered"

        # Run the background task manually — no embedding mock needed,
        # it should fail before reaching that point
        await captured["func"](*captured["args"], **captured["kwargs"])

        result = await db_session.execute(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == candidate.id
            )
        )
        doc = result.scalar_one_or_none()

        assert doc is not None, "Document record was never created"
        assert doc.error_message is not None
        assert "no readable text" in doc.error_message
