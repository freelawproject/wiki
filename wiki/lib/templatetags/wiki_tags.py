import json
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from wiki.lib.users import display_name as _display_name

register = template.Library()

_BACKTICK_RE = re.compile(r"`([^`]+)`")


@register.filter
def inline_code(title):
    """Convert `backtick` spans in a title to <code> tags.

    For use in HTML elements that support markup (e.g. <h1>).
    The non-backtick parts are escaped to prevent XSS.
    """
    parts = _BACKTICK_RE.split(str(title))
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(escape(part))
        else:
            out.append(f"<code>{escape(part)}</code>")
    return mark_safe("".join(out))


@register.filter
def strip_backticks(title):
    """Remove backtick markers from a title for plain-text contexts (e.g. <title>)."""
    return _BACKTICK_RE.sub(r"\1", str(title))


@register.filter
def display_name(user):
    """Return display name for a user, never showing a full email."""
    return _display_name(user)


@register.filter
def username_local(user):
    """Return the local part of a user's email username (before the @)."""
    username = getattr(user, "username", "")
    if "@" in username:
        return username.split("@")[0]
    return username


@register.filter
def json_encode(value):
    """JSON-serialize a value for use in HTML data attributes."""
    return mark_safe(json.dumps(value))
