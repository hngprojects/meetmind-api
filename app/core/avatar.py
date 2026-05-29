import hashlib
import uuid

# Preset distinct hex colors
COLORS = [
    "#FF5733",
    "#33FF57",
    "#3357FF",
    "#F033FF",
    "#FF33A8",
    "#33FFF0",
    "#FFC300",
    "#FF3333",
]


def get_avatar_initials(name: str | None, email: str | None) -> str:
    """Compute initials from name or email."""
    if name and name.strip():
        parts = name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return name.strip()[:2].upper()
    if email and email.strip():
        local_part = email.split("@")[0]
        return local_part[:2].upper()
    return "NA"


def get_avatar_color(identifier: str | uuid.UUID) -> str:
    """Deterministic color assignment based on UUID."""
    if not identifier:
        return COLORS[0]
    id_str = str(identifier).replace("-", "")
    try:
        hash_val = int(hashlib.md5(id_str.encode()).hexdigest(), 16)
        return COLORS[hash_val % len(COLORS)]
    except ValueError:
        return COLORS[0]
