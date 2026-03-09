"""Advanced search query parser for the wiki.

Extracts structured filters from a raw query string, returning
a ParsedQuery dataclass that the search module can translate
into ORM filters.

Parsing order (important for correctness):
1. Extract "quoted phrases" first — protects colons inside quotes
2. Extract filter:value pairs
3. Extract -excluded terms
4. Remainder is free text
"""

import re
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ParsedQuery:
    text: str = ""
    phrases: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    title_terms: list[str] = field(default_factory=list)
    content_terms: list[str] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    visibility: str | None = None
    before_date: date | None = None
    after_date: date | None = None


# Patterns
_PHRASE_RE = re.compile(r'"([^"]*)"')
_FILTER_RE = re.compile(
    r"\b(title|content|in|owner|visibility|is|before|after):(\S+)"
)
_EXCLUDE_RE = re.compile(r"(?:^|\s)-(\S+)")


def _parse_date(value: str) -> date | None:
    """Parse YYYY-MM-DD, returning None for invalid dates."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_query(raw: str) -> ParsedQuery:
    """Parse a raw search query string into structured filters."""
    result = ParsedQuery()

    if not raw or not raw.strip():
        return result

    text = raw

    # 1. Extract quoted phrases (protects colons inside quotes)
    for match in _PHRASE_RE.finditer(text):
        phrase = match.group(1).strip()
        if phrase:
            result.phrases.append(phrase)
    text = _PHRASE_RE.sub("", text)

    # 2. Extract filter:value pairs
    for match in _FILTER_RE.finditer(text):
        key = match.group(1).lower()
        value = match.group(2)

        if key == "title":
            result.title_terms.append(value)
        elif key == "content":
            result.content_terms.append(value)
        elif key == "in":
            result.directories.append(value)
        elif key == "owner":
            result.owners.append(value)
        elif key in ("visibility", "is"):
            result.visibility = value.lower()
        elif key == "before":
            result.before_date = _parse_date(value)
        elif key == "after":
            result.after_date = _parse_date(value)
    text = _FILTER_RE.sub("", text)

    # 3. Extract -excluded terms
    for match in _EXCLUDE_RE.finditer(text):
        result.excluded.append(match.group(1))
    text = _EXCLUDE_RE.sub("", text)

    # 4. Remainder is free text
    result.text = " ".join(text.split())

    return result
