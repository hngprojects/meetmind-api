from sdk.wake_words import detect_wake_word, normalize_wake_words


def test_normalize_wake_words_removes_case_insensitive_duplicates():
    assert normalize_wake_words(["MeetMind", " meetmind ", "Hey MeetMind"]) == [
        "MeetMind",
        "Hey MeetMind",
    ]


def test_detect_wake_word_respects_configured_phrases():
    wake_words = ["Atlas", "Hey Atlas"]

    assert detect_wake_word("Can you help here, Hey Atlas?", wake_words) == "Hey Atlas"
    assert detect_wake_word("MeetMind should not trigger", wake_words) is None


def test_detect_wake_word_ignores_blank_phrases():
    assert detect_wake_word("This text has normal word boundaries.", [" ", ""]) is None
