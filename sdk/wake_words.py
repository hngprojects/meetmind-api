from __future__ import annotations

import re


def normalize_wake_words(wake_words: list[str] | None) -> list[str]:
    if not wake_words:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for word in wake_words:
        cleaned = word.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            normalized.append(cleaned)
    return normalized


def detect_wake_word(text: str, wake_words: list[str]) -> str | None:
    lowered = text.lower()
    for wake_word in sorted(wake_words, key=len, reverse=True):
        pattern = rf"\b{re.escape(wake_word.lower())}\b"
        if re.search(pattern, lowered):
            return wake_word
    return None
