"""Formatting utilities — pure functions, no DB, no side effects.

These are shared across interviews, calendar, and candidates modules.
All functions accept explicit 'now' parameters so tests never need
to mock datetime.now().
"""

from datetime import datetime, timezone


def time_display(dt: datetime | None, now: datetime | None = None) -> str | None:
    """Return a human-readable relative time string for a scheduled datetime.

    Examples:
        today at 10:00–10:30   → "Today 10:00AM - 10:30AM"
        tomorrow               → "Tomorrow 10:00AM - 10:30AM"
        other date             → "Fri Jun 13 10:00AM"

    This function only formats the start time. For a range display
    (start → end), use time_range_display.

    Args:
        dt:  The datetime to format. Returns None if dt is None.
        now: Anchor for "today"/"tomorrow" comparison. Defaults to UTC now.
    """
    if dt is None:
        return None

    if now is None:
        now = datetime.now(timezone.utc)

    # Normalise both to UTC-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    dt_date = dt.date()
    now_date = now.date()

    time_str = dt.strftime("%-I:%M%p")  # e.g. "10:00AM"

    if dt_date == now_date:
        return f"Today {time_str}"
    if (dt_date - now_date).days == 1:
        return f"Tomorrow {time_str}"
    return dt.strftime("%a %b %-d ") + time_str


def time_range_display(
    start: datetime | None,
    end: datetime | None,
    now: datetime | None = None,
) -> str | None:
    """Return a range display like "Tomorrow 10:00AM - 10:30AM".

    Used by the calendar and interview list to show a slot at a glance.
    """
    if start is None:
        return None

    if now is None:
        now = datetime.now(timezone.utc)

    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    start_date = start.date()
    now_date = now.date()

    start_time = start.strftime("%-I:%M%p")
    end_time = end.strftime("%-I:%M%p") if end else None

    if start_date == now_date:
        prefix = "Today"
    elif (start_date - now_date).days == 1:
        prefix = "Tomorrow"
    else:
        prefix = start.strftime("%a %b %-d")

    if end_time:
        return f"{prefix} {start_time} - {end_time}"
    return f"{prefix} {start_time}"


def date_display(dt: datetime | None) -> str | None:
    """Return a human-readable date string like 'May 2, 2025'.

    Used by candidates list and interview profile.
    """
    if dt is None:
        return None
    return dt.strftime("%B %-d, %Y")


def elapsed_display(seconds: int | None) -> str:
    """Format elapsed seconds as HH:MM:SS.

    Examples:
        0      → "00:00:00"
        94     → "00:01:34"
        1874   → "00:31:14"
        3661   → "01:01:01"
    """
    if seconds is None:
        return "00:00:00"
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:02}"