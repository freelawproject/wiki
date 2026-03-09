"""Markdown rendering with wiki link resolution.

Wiki links use the syntax #page-slug. During rendering, these are
resolved to actual page URLs or shown as red links for missing pages.
"""

import re

import markdown2
import nh3

WIKI_LINK_RE = re.compile(r"(?<!\w)#([a-z0-9]+(?:-[a-z0-9]+)*)")

ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "a",
    "ul",
    "ol",
    "li",
    "code",
    "pre",
    "blockquote",
    "em",
    "strong",
    "del",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "br",
    "hr",
    "img",
    "span",
    "div",
    "input",
    "label",
    "sup",
    "sub",
    "dl",
    "dt",
    "dd",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "input": {"type", "checked", "disabled"},
    "span": {"class"},
    "th": {"align"},
    "td": {"align"},
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "h5": {"id"},
    "h6": {"id"},
    "code": {"class"},
}

ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


class MarkdownResult(str):
    """String subclass that carries a toc_html attribute."""

    toc_html = ""


def _sanitize(html):
    """Sanitize HTML through nh3.

    SECURITY: markdown2 passes raw HTML through unchanged, so user
    content like ``<script>`` or ``<img onerror=...>`` would execute.
    This function strips all tags/attributes not in the allowlists.
    """
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
    )


def resolve_wiki_links(content):
    """Replace #slug references with proper markdown links.

    Known slugs become [Title](/dir/path/slug).
    Unknown slugs become red links.
    """
    from wiki.pages.models import Page, SlugRedirect

    slugs = set(WIKI_LINK_RE.findall(content))
    if not slugs:
        return content

    # Build a slug → page mapping
    pages = Page.objects.filter(slug__in=slugs).select_related("directory")
    slug_map = {p.slug: p for p in pages}

    # Check redirects for slugs not found directly
    missing = slugs - set(slug_map.keys())
    if missing:
        redirects = SlugRedirect.objects.filter(
            old_slug__in=missing
        ).select_related("page__directory")
        for r in redirects:
            slug_map[r.old_slug] = r.page

    def replace_link(match):
        slug = match.group(1)
        if slug in slug_map:
            page = slug_map[slug]
            url = page.get_absolute_url()
            return f"[{page.title}]({url})"
        else:
            return f'<span class="text-red-500 dark:text-red-400" title="Page not found">#{slug}</span>'

    return WIKI_LINK_RE.sub(replace_link, content)


# ── Markdown stripping (plain-text extraction) ──────────────────────

_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_BOLD_ITALIC_RE = re.compile(r"\*{1,3}|_{1,3}")
_STRIKETHROUGH_RE = re.compile(r"~~")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HR_RE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^>\s?", re.MULTILINE)
_UL_RE = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_OL_RE = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")


def strip_markdown(text: str) -> str:
    """Convert markdown to plain text by removing all formatting syntax.

    Strips heading markers, code blocks, links, emphasis, images, HTML
    tags, blockquotes, list markers, and horizontal rules. Heading text,
    link text, and inline-code content are preserved.
    """
    if not text:
        return ""

    text = _FENCED_CODE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _HEADING_RE.sub("", text)
    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLD_ITALIC_RE.sub("", text)
    text = _STRIKETHROUGH_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _HR_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _UL_RE.sub("", text)
    text = _OL_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def render_markdown(content):
    """Render markdown content to HTML with wiki link resolution and TOC."""
    content = resolve_wiki_links(content)
    html = markdown2.markdown(
        content,
        extras=[
            "fenced-code-blocks",
            "tables",
            "header-ids",
            "toc",
            "strike",
            "task_list",
            "cuddled-lists",
        ],
    )
    toc = getattr(html, "toc_html", "")
    result = MarkdownResult(_sanitize(str(html)))
    result.toc_html = _sanitize(toc) if toc else ""
    return result
