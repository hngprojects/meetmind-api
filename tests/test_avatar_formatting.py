"""
Unit tests for app/core/avatar.py and app/core/formatting.py.

Pure function tests — no DB, no fixtures, no async.
Each test corresponds to one behavior from the TDD plan.
"""

from datetime import datetime, timezone

from app.core.avatar import avatar_initials, avatar_color, AVATAR_COLORS
from app.core.formatting import time_display, time_range_display, date_display, elapsed_display


class TestAvatarInitials:
    def test_two_word_name_uses_first_and_last_initials(self):
        assert avatar_initials("Frank Udoho") == "FU"

    def test_three_word_name_uses_first_and_last_word(self):
        assert avatar_initials("Mary Jane Watson") == "MW"

    def test_single_word_name_uses_first_two_letters(self):
        assert avatar_initials("Frank") == "FR"

    def test_result_is_always_uppercase(self):
        assert avatar_initials("frank udoho") == "FU"

    def test_none_name_falls_back_to_email(self):
        assert avatar_initials(None, email="frankudoho@gmail.com") == "FR"

    def test_none_name_and_none_email_returns_question_marks(self):
        assert avatar_initials(None) == "??"

    def test_empty_string_name_falls_back_to_email(self):
        assert avatar_initials("", email="abc@test.com") == "AB"

    def test_single_letter_name_doubles_it(self):
        assert avatar_initials("X") == "XX"


class TestAvatarColor:
    def test_returns_a_hex_color_string(self):
        import uuid
        color = avatar_color(uuid.uuid4())
        assert color.startswith("#")
        assert len(color) == 7

    def test_same_id_returns_same_color(self):
        import uuid
        uid = uuid.uuid4()
        assert avatar_color(uid) == avatar_color(uid)

    def test_returns_a_color_from_the_preset_list(self):
        import uuid
        color = avatar_color(uuid.uuid4())
        assert color in AVATAR_COLORS

    def test_works_with_string_id(self):
        color = avatar_color("some-string-id")
        assert color in AVATAR_COLORS


class TestTimeDisplay:
    def _now(self):
        return datetime(2025, 6, 13, 9, 0, 0, tzinfo=timezone.utc)

    def test_today_returns_today_prefix(self):
        dt = datetime(2025, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
        assert time_display(dt, now=self._now()).startswith("Today")

    def test_tomorrow_returns_tomorrow_prefix(self):
        dt = datetime(2025, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
        assert time_display(dt, now=self._now()).startswith("Tomorrow")

    def test_other_date_has_no_today_or_tomorrow_prefix(self):
        dt = datetime(2025, 6, 20, 10, 0, 0, tzinfo=timezone.utc)
        result = time_display(dt, now=self._now())
        assert not result.startswith("Today")
        assert not result.startswith("Tomorrow")

    def test_none_dt_returns_none(self):
        assert time_display(None) is None

    def test_naive_datetime_is_handled(self):
        dt = datetime(2025, 6, 13, 10, 0, 0)
        now = datetime(2025, 6, 13, 9, 0, 0, tzinfo=timezone.utc)
        assert time_display(dt, now=now).startswith("Today")


class TestTimeRangeDisplay:
    def _now(self):
        return datetime(2025, 6, 13, 9, 0, 0, tzinfo=timezone.utc)

    def test_today_range_has_today_prefix_and_separator(self):
        start = datetime(2025, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2025, 6, 13, 10, 30, 0, tzinfo=timezone.utc)
        result = time_range_display(start, end, now=self._now())
        assert result.startswith("Today")
        assert " - " in result

    def test_tomorrow_range_has_tomorrow_prefix(self):
        start = datetime(2025, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
        end   = datetime(2025, 6, 14, 10, 30, 0, tzinfo=timezone.utc)
        assert time_range_display(start, end, now=self._now()).startswith("Tomorrow")

    def test_none_start_returns_none(self):
        assert time_range_display(None, None) is None

    def test_no_end_time_omits_range_separator(self):
        start = datetime(2025, 6, 13, 10, 0, 0, tzinfo=timezone.utc)
        assert " - " not in time_range_display(start, None, now=self._now())


class TestDateDisplay:
    def test_formats_as_month_day_year(self):
        assert date_display(datetime(2025, 5, 2, tzinfo=timezone.utc)) == "May 2, 2025"

    def test_june_10_2026(self):
        assert date_display(datetime(2026, 6, 10, tzinfo=timezone.utc)) == "June 10, 2026"

    def test_none_returns_none(self):
        assert date_display(None) is None


class TestElapsedDisplay:
    def test_zero_seconds(self):
        assert elapsed_display(0) == "00:00:00"

    def test_94_seconds(self):
        assert elapsed_display(94) == "00:01:34"

    def test_1874_seconds(self):
        assert elapsed_display(1874) == "00:31:14"

    def test_3661_seconds(self):
        assert elapsed_display(3661) == "01:01:01"

    def test_none_returns_zero_string(self):
        assert elapsed_display(None) == "00:00:00"

    def test_negative_seconds_treated_as_zero(self):
        assert elapsed_display(-5) == "00:00:00"