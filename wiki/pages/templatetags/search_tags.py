"""Template filters for search result display."""

import re

from django import template
from django.utils.safestring import mark_safe

from wiki.lib.markdown import strip_markdown as _strip_markdown

register = template.Library()

# <mark> tags inserted by ts_headline for search highlighting must survive
# stripping.  We temporarily swap them out, strip, then restore.
_MARK_OPEN = re.compile(r"<mark>")
_MARK_CLOSE = re.compile(r"</mark>")
_PLACEHOLDER_OPEN = "\x00MARKOPEN\x00"
_PLACEHOLDER_CLOSE = "\x00MARKCLOSE\x00"


@register.filter
def strip_markdown(text):
    """Strip markdown syntax from text, preserving <mark> tags."""
    if not text:
        return ""
    # Protect <mark> tags from the HTML-tag stripping pass
    text = _MARK_OPEN.sub(_PLACEHOLDER_OPEN, text)
    text = _MARK_CLOSE.sub(_PLACEHOLDER_CLOSE, text)
    text = _strip_markdown(text)
    text = text.replace(_PLACEHOLDER_OPEN, "<mark>")
    text = text.replace(_PLACEHOLDER_CLOSE, "</mark>")
    # ts_headline escapes HTML entities by default, so only <mark> tags remain
    return mark_safe(text)
