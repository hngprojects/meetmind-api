import pytest

from sdk.providers.zoom_rtms.oauth_state import (
    ZoomOAuthStateError,
    create_oauth_state,
    validate_oauth_state,
)


def test_oauth_state_round_trip_validates_signature():
    state = create_oauth_state("state-secret")

    validate_oauth_state(state, "state-secret")


def test_oauth_state_rejects_tampering():
    state = create_oauth_state("state-secret")
    tampered = state.replace(".", "x.", 1)

    with pytest.raises(ZoomOAuthStateError):
        validate_oauth_state(tampered, "state-secret")


def test_oauth_state_requires_secret():
    with pytest.raises(ZoomOAuthStateError):
        create_oauth_state("")
