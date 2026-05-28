"""Avatar utility — shared across interviews, candidates, and calendar modules.

avatar_initials and avatar_color are pure functions.
They never touch the DB and are safe to call anywhere.
"""

AVATAR_COLORS = [
    "#0D7377",
    "#E67E22",
    "#C0392B",
    "#27AE60",
    "#7C3AED",
    "#2980B9",
    "#D35400",
    "#16A085",
]


def avatar_initials(name: str | None, email: str | None = None) -> str:
    """Return 2-character uppercase initials.

    Rules:
    - "Frank Udoho"  → "FU"  (first letter of first + last word)
    - "Frank"        → "FR"  (single word → first two letters)
    - None + email   → first two letters of email local part
    - None + None    → "??"
    """
    if name and name.strip():
        parts = name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        word = parts[0]
        return (word[:2]).upper() if len(word) >= 2 else (word[0] * 2).upper()

    if email and "@" in email:
        local = email.split("@")[0]
        cleaned = "".join(c for c in local if c.isalpha())
        if len(cleaned) >= 2:
            return cleaned[:2].upper()
        if cleaned:
            return (cleaned[0] * 2).upper()

    return "??"


def avatar_color(entity_id: object) -> str:
    """Return a deterministic hex color for an entity.

    Takes any hashable id (UUID, str, int).
    Same id → same color every time. No DB involved.
    """
    index = abs(hash(str(entity_id))) % len(AVATAR_COLORS)
    return AVATAR_COLORS[index]