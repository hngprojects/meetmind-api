import uuid

from app.models.base import Base, generate_uuid_v7


class TestUUIDv7Generation:
    def test_generates_valid_uuid(self):
        result = generate_uuid_v7()
        assert isinstance(result, uuid.UUID)

    def test_generates_uuid_version_7(self):
        result = generate_uuid_v7()
        assert result.version == 7

    def test_generates_unique_ids(self):
        ids = {generate_uuid_v7() for _ in range(100)}
        assert len(ids) == 100

    def test_ids_are_time_ordered(self):
        import time

        id1 = generate_uuid_v7()
        time.sleep(0.002)  # ensure different millisecond
        id2 = generate_uuid_v7()
        # UUID v7 timestamp is in the first 48 bits; later time == larger int
        assert id1.int < id2.int


class TestBaseMetadata:
    def test_all_expected_tables_registered(self):
        expected = {
            "users",
            "sso_providers",
            "password_reset_tokens",
            "active_sessions",
            "user_meeting_preferences",
            "user_interview_preferences",
            "user_notification_preferences",
            "user_privacy_settings",
            "user_security_settings",
            "workspaces",
            "workspace_members",
            "workspace_invites",
            "user_platform_integrations",
            "user_trials",
            "integrations",
            "integration_channels",
            "integration_settings",
            "waitlist_signups",
            "meetings",
            "meeting_participants",
            "meeting_comments",
            "transcripts",
            "transcript_segments",
            "meeting_summaries",
            "summary_keypoints",
            "summary_decisions",
            "action_items",
            "ask_mind_sessions",
            "ask_mind_messages",
            "ask_mind_suggested_prompts",
            "candidates",
            "interviews",
            "interview_transcripts",
            "interview_transcript_turns",
            "interview_summaries",
            "interview_skills_to_assess",
            "interview_highlights",
            "interview_red_flags",
            "scorecard_categories",
            "interview_scorecards",
            "scorecard_scores",
            "scorecard_questions",
            "scorecard_signals",
            "refresh_tokens",
            "candidate_documents",
            "document_chunks",
        }
        actual = set(Base.metadata.tables.keys())
        assert expected.issubset(actual)

    def test_table_count(self):
        assert len(Base.metadata.tables) == 49


class TestUUIDPrimaryKeyMixin:
    def test_all_tables_have_uuid_primary_key(self):
        for name, table in Base.metadata.tables.items():
            pk_cols = [c for c in table.columns if c.primary_key]
            assert len(pk_cols) == 1, f"{name} should have exactly 1 PK column"
            assert pk_cols[0].name == "id", f"{name} PK should be named 'id'"


class TestForeignKeys:
    def test_users_table_has_no_foreign_keys(self):
        users = Base.metadata.tables["users"]
        assert len(users.foreign_keys) == 0

    def test_sso_providers_references_users(self):
        table = Base.metadata.tables["sso_providers"]
        fk_targets = {fk.column.table.name for fk in table.foreign_keys}
        assert "users" in fk_targets

    def test_workspace_members_references_both(self):
        table = Base.metadata.tables["workspace_members"]
        fk_targets = {fk.column.table.name for fk in table.foreign_keys}
        assert "users" in fk_targets
        assert "workspaces" in fk_targets

    def test_meetings_references_workspaces_and_users(self):
        table = Base.metadata.tables["meetings"]
        fk_targets = {fk.column.table.name for fk in table.foreign_keys}
        assert "workspaces" in fk_targets
        assert "users" in fk_targets

    def test_transcript_segments_references_transcripts(self):
        table = Base.metadata.tables["transcript_segments"]
        fk_targets = {fk.column.table.name for fk in table.foreign_keys}
        assert "transcripts" in fk_targets

    def test_interviews_references_candidates_and_users(self):
        table = Base.metadata.tables["interviews"]
        fk_targets = {fk.column.table.name for fk in table.foreign_keys}
        assert "candidates" in fk_targets
        assert "users" in fk_targets
        assert "workspaces" in fk_targets


class TestUniqueConstraints:
    def test_users_email_is_unique(self):
        users = Base.metadata.tables["users"]
        email_col = users.c.email
        # Check column is in a unique constraint or has unique=True
        unique_cols = {
            col.name
            for constraint in users.constraints
            if hasattr(constraint, "columns")
            for col in constraint.columns
            if getattr(constraint, "unique", False)
            or constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert "email" in unique_cols or email_col.unique

    def test_workspace_members_has_composite_unique(self):
        table = Base.metadata.tables["workspace_members"]
        unique_constraints = [
            c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
        ]
        assert len(unique_constraints) >= 1
        col_names = {col.name for col in unique_constraints[0].columns}
        assert col_names == {"workspace_id", "user_id"}


class TestIndexes:
    def test_transcript_segments_has_sequence_index(self):
        table = Base.metadata.tables["transcript_segments"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_transcript_segments_transcript_seq" in index_names

    def test_interviews_has_workspace_candidate_index(self):
        table = Base.metadata.tables["interviews"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_interviews_workspace_candidate" in index_names

    def test_interviews_has_interviewer_start_index(self):
        table = Base.metadata.tables["interviews"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_interviews_interviewer_start" in index_names
