"""Template filters for search result display."""

import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# Patterns to strip common markdown syntax while preserving <mark> tags
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HEADER_RE = re.compile(r"#{1,6}\s+")
_BOLD_ITALIC_RE = re.compile(r"(\*{1,3}|_{1,3})(.*?)\1")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BLOCKQUOTE_RE = re.compile(r"^>\s+", re.MULTILINE)
_HR_RE = re.compile(r"^[-*]{3,}\s*$", re.MULTILINE)
_LIST_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)


@register.filter
def strip_markdown(text):
    """Strip markdown syntax from text, preserving <mark> tags."""
    if not text:
        return ""
    text = _LINK_RE.sub(r"\1", text)
    text = _HEADER_RE.sub("", text)
    text = _BOLD_ITALIC_RE.sub(r"\2", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _HR_RE.sub("", text)
    text = _LIST_RE.sub("", text)
    text = _NUMBERED_LIST_RE.sub("", text)
    # ts_headline escapes HTML entities by default, so only <mark> tags remain
    return mark_safe(text.strip())
