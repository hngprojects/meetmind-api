import pytest
from pydantic import ValidationError

from sdk.schemas import SpeakRequest


def test_speak_request_rejects_blank_text():
    with pytest.raises(ValidationError):
        SpeakRequest(text="   ")


def test_speak_request_accepts_non_blank_text():
    assert SpeakRequest(text="Hello").text == "Hello"
