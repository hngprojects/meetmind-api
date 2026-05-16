from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sdk.db import SDKBase
from sdk.repositories import SDKRepository


def test_session_and_transcript_persist_in_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'sdk.sqlite').as_posix()}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    SDKBase.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        repo = SDKRepository(db)
        session = repo.create_session(
            platform="zoom",
            meeting_id="123456789",
            meeting_url="https://zoom.us/j/123456789",
            agent_name="Atlas",
            context="Interview for backend role",
            wake_words=["Atlas", "Hey Atlas"],
        )

        repo.add_transcript_turn(
            session=session,
            source="zoom_rtms",
            role="human",
            speaker_name="Candidate",
            speaker_id="user-1",
            content="Hey Atlas, what should we ask next?",
            timestamp_ms=1200,
            provider_stream_id="stream-1",
            trigger_reason="wake_word:Hey Atlas",
        )

        turns = repo.list_transcript(session.id)
        assert session.wake_words == ["Atlas", "Hey Atlas"]
        assert len(turns) == 1
        assert turns[0].sequence_no == 1
        assert turns[0].content == "Hey Atlas, what should we ask next?"
        assert turns[0].trigger_reason == "wake_word:Hey Atlas"
    finally:
        db.close()
