# tests/test_candidates.py
"""
Tests for candidate search, get-by-ID, and export endpoints.

Test naming follows the repo convention:
test_<action>_<expected_outcome>_<condition>
"""

import uuid

import pytest

from app.models.interview import Candidate
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

CANDIDATE_URL = "/api/v1/candidates"
SEARCH_URL = "/api/v1/candidates/search"
EXPORT_URL = "/api/v1/candidates/export"


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


# ─── Get Candidate by ID Tests ──────────────────────────────────────────────


class TestCandidateGetByID:
    @pytest.mark.anyio
    async def test_get_returns_200_with_candidate_data(self, client, db_session):
        """Fetching an existing candidate by UUID returns 200 with full profile."""
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        candidate = await create_candidate(
            db_session, workspace.id, "Adaobi Nwosu", "adaobi@example.com"
        )

        response = await client.get(
            f"{CANDIDATE_URL}/{candidate.id}",
            headers=auth_header(token),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["id"] == str(candidate.id)
        assert data["full_name"] == "Adaobi Nwosu"
        assert data["email"] == "adaobi@example.com"
        assert data["workspace_id"] == str(workspace.id)

    @pytest.mark.anyio
    async def test_get_returns_404_for_nonexistent_id(self, client, db_session):
        """Fetching a UUID that does not exist returns 404."""
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        missing_id = uuid.uuid4()
        response = await client.get(
            f"{CANDIDATE_URL}/{missing_id}",
            headers=auth_header(token),
        )

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "candidate_not_found"

    @pytest.mark.anyio
    async def test_get_returns_404_for_cross_workspace_access(self, client, db_session):
        """A candidate from another workspace is invisible — returns 404."""
        from app.services.auth import AuthService

        user_a, workspace_a = await create_user_with_workspace(db_session)
        user_b, workspace_b = await create_user_with_workspace(db_session)

        candidate = await create_candidate(db_session, workspace_a.id, "Chidi Okonkwo")

        token_b = await AuthService.create_access_token(user_b)
        response = await client.get(
            f"{CANDIDATE_URL}/{candidate.id}",
            headers=auth_header(token_b),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_get_returns_422_for_invalid_uuid(self, client, db_session):
        """A non-UUID path parameter returns 422."""
        from app.services.auth import AuthService

        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            f"{CANDIDATE_URL}/not-a-uuid",
            headers=auth_header(token),
        )

        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_get_returns_401_without_token(self, client, db_session):
        """An unauthenticated request returns 401."""
        candidate_id = uuid.uuid4()
        response = await client.get(f"{CANDIDATE_URL}/{candidate_id}")
        assert response.status_code == 401
