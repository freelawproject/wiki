"""Helpers shared by the apps that send notification email."""

from django.template.defaultfilters import date as date_filter
from django.utils import timezone

# The original is quoted back in full, but a pathologically long one would
# bury the response it's meant to give context to.
MAX_QUOTED_CHARS = 2000


def quote_original(message, submitted_at=None, label="Your original message"):
    """Render someone's own submission as an email-style quoted block.

    A reply can land months after the message that prompted it, by which
    point the recipient has usually forgotten what they wrote. Every
    "someone responded to you" email therefore quotes the original back,
    with the date it was sent.

    Returns "" when there's nothing to quote, so callers can interpolate
    the result unconditionally.
    """
    text = (message or "").strip()
    if not text:
        return ""

    truncated = len(text) > MAX_QUOTED_CHARS
    if truncated:
        text = text[:MAX_QUOTED_CHARS].rstrip()

    quoted = "\n".join(f"> {line}".rstrip() for line in text.splitlines())
    if truncated:
        quoted += "\n> […]"

    heading = label
    if submitted_at is not None:
        if timezone.is_aware(submitted_at):
            submitted_at = timezone.localtime(submitted_at)
        heading = f"{label}, sent {date_filter(submitted_at, 'F j, Y')}"

    return f"{heading}:\n\n{quoted}\n\n"
