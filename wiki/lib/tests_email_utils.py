"""Tests for the shared notification-email helpers."""

import datetime

from django.utils import timezone

from wiki.lib.email_utils import MAX_QUOTED_CHARS, quote_original


class TestQuoteOriginal:
    def test_quotes_message_with_date(self):
        """The original is quoted with the date it was sent."""
        sent = timezone.make_aware(datetime.datetime(2026, 3, 4, 12, 0))
        out = quote_original(
            "Please fix the intro.", sent, label="Your original comment"
        )
        assert "Your original comment, sent March 4, 2026:" in out
        assert "> Please fix the intro." in out

    def test_uses_local_time_for_the_date(self):
        """Late-evening UTC timestamps show the reader's local date."""
        # 2026-03-05 04:00 UTC is still March 4th in America/Los_Angeles.
        sent = datetime.datetime(
            2026, 3, 5, 4, 0, tzinfo=datetime.timezone.utc
        )
        assert "March 4, 2026" in quote_original("Hi", sent)

    def test_quotes_every_line(self):
        """Multi-line messages get a quote marker per line."""
        out = quote_original("First line\nSecond line")
        assert "> First line\n> Second line" in out

    def test_blank_lines_do_not_get_trailing_space(self):
        """Quoted blank lines are a bare ">", not "> "."""
        out = quote_original("First\n\nSecond")
        assert "> First\n>\n> Second" in out

    def test_omits_date_when_unknown(self):
        """Without a timestamp the heading is just the label."""
        out = quote_original("Hello", None, label="Your original comment")
        assert out.startswith("Your original comment:\n\n")

    def test_naive_datetime_does_not_raise(self):
        """A naive timestamp is formatted as-is rather than blowing up."""
        naive = datetime.datetime(2026, 3, 4, 12, 0)
        assert "March 4, 2026" in quote_original("Hello", naive)

    def test_empty_message_yields_empty_string(self):
        """Nothing to quote means nothing is added to the email."""
        assert quote_original("") == ""
        assert quote_original("   \n  ") == ""
        assert quote_original(None) == ""

    def test_long_message_is_truncated(self):
        """A huge original can't bury the response it accompanies."""
        out = quote_original("x" * (MAX_QUOTED_CHARS + 500))
        assert len(out) < MAX_QUOTED_CHARS + 200
        assert out.rstrip().endswith("> […]")

    def test_short_message_is_not_truncated(self):
        """Ordinary messages are quoted in full."""
        out = quote_original("x" * MAX_QUOTED_CHARS)
        assert "[…]" not in out
