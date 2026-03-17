"""Markdown rendering with wiki link resolution.

Wiki links use the syntax #page-slug. During rendering, these are
resolved to actual page URLs or shown as red links for missing pages.
"""

import re
from urllib.parse import urlparse

import markdown2
import nh3
from django.conf import settings

from wiki.lib.inheritance import resolve_effective_value

# ── Alert types (GitHub-style) ───────────────────────────────────────
_ALERT_TITLES = {
    "NOTE": "Note",
    "TIP": "Tip",
    "IMPORTANT": "Important",
    "WARNING": "Warning",
    "CAUTION": "Caution",
}

# Matches blockquotes starting with [!TYPE] (runs on sanitized HTML)
_ALERT_BLOCKQUOTE_RE = re.compile(
    r"<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]"
    r"\s*(?:<br\s*/?>)?\s*"
    r"(.*?)</blockquote>",
    re.DOTALL | re.IGNORECASE,
)

# Matches links followed by {button} suffix (runs on sanitized HTML)
_BUTTON_LINK_RE = re.compile(
    r'(<a\s[^>]*href="[^"]*"[^>]*)>(.*?)</a>'
    r"\s*\{button(?:-(outline|danger))?\}",
    re.DOTALL,
)

WIKI_LINK_RE = re.compile(r"(?<!\w)(?<!\()#([a-z0-9]+(?:-[a-z0-9]+)*)")

# Matches [text](#slug) markdown links where #slug is a wiki page reference
_MD_LINK_WIKI_RE = re.compile(r"\[([^\]]+)\]\(#([a-z0-9]+(?:-[a-z0-9]+)*)\)")

# Matches reference-style link definitions: [ref]: #slug
_REF_LINK_WIKI_RE = re.compile(
    r"^(\[[^\]]+\]:\s*)#([a-z0-9]+(?:-[a-z0-9]+)*)\s*$",
    re.MULTILINE,
)

# Pattern for auto-linking bare URLs (used by markdown2 link-patterns extra)
_AUTOLINK_RE = re.compile(r"(?<!\()(https?://[^\s<>\)\]\"]+)")

# Matches internal wiki URLs — full (https://domain/c/path) or relative (/c/path)
# Used to detect internal links for PageLink tracking.
_INTERNAL_URL_RE = re.compile(
    r"(?:"
    r"\[(?:[^\]]*)\]\((/c/[^)\s]+)\)"  # markdown link with relative path
    r"|"
    r"\[(?:[^\]]*)\]\((https?://[^)\s]+/c/[^)\s]+)\)"  # markdown link with full URL
    r"|"
    r"(?<!\()(/c/[^\s<>\)\]\"]+)"  # bare relative path
    r"|"
    r"(https?://[^\s<>\)\]\"]+/c/[^\s<>\)\]\"]+)"  # bare full URL
    r")"
)


def extract_slugs_from_internal_urls(content):
    """Extract page slugs from internal wiki URLs in content.

    Finds URLs like /c/dir/slug or {BASE_URL}/c/dir/slug and returns
    the set of slugs (last path segment).
    """
    base_url = getattr(settings, "BASE_URL", "")
    base_host = urlparse(base_url).hostname or ""
    slugs = set()
    for match in _INTERNAL_URL_RE.finditer(content):
        url = (
            match.group(1)
            or match.group(2)
            or match.group(3)
            or match.group(4)
        )
        if not url:
            continue
        # For full URLs, verify the domain matches BASE_URL
        if url.startswith("http"):
            parsed = urlparse(url)
            if parsed.hostname != base_host:
                continue
            path = parsed.path
        else:
            path = url
        # Strip /c/ prefix and trailing slash, extract last segment as slug
        path = path.rstrip("/")
        if not path.startswith("/c/"):
            continue
        content_path = path[3:]  # remove "/c/"
        # Skip action URLs like .../edit/, .../history/, etc.
        action_suffixes = (
            "/edit",
            "/move",
            "/delete",
            "/history",
            "/backlinks",
            "/permissions",
            "/diff",
            "/revert",
            "/subscribe",
            "/feedback",
        )
        if any(content_path.endswith(s) for s in action_suffixes):
            continue
        slug = content_path.rsplit("/", 1)[-1]
        if slug:
            slugs.add(slug)
    return slugs


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

    Handles three syntaxes:
    - Standalone: #slug → [Title](/dir/path/slug)
    - Inline link: [text](#slug) → [text](/dir/path/slug)
    - Reference link: [ref]: #slug → [ref]: /dir/path/slug

    Known slugs are resolved to page URLs. Unknown standalone slugs
    become red links. Unknown slugs in [text](#slug) and reference
    definitions are left as-is (they may be heading anchors).
    """
    # Inline import to avoid circular dependency (pages/models ↔ lib/markdown)
    from wiki.pages.models import Page, SlugRedirect

    # Collect slugs from all three patterns
    standalone_slugs = set(WIKI_LINK_RE.findall(content))
    md_link_slugs = {m.group(2) for m in _MD_LINK_WIKI_RE.finditer(content)}
    ref_link_slugs = {m.group(2) for m in _REF_LINK_WIKI_RE.finditer(content)}
    all_slugs = standalone_slugs | md_link_slugs | ref_link_slugs

    if not all_slugs:
        return content

    # Build a slug → page mapping
    pages = Page.objects.filter(slug__in=all_slugs).select_related("directory")
    slug_map = {p.slug: p for p in pages}

    # Check redirects for slugs not found directly
    missing = all_slugs - set(slug_map.keys())
    if missing:
        redirects = SlugRedirect.objects.filter(
            old_slug__in=missing
        ).select_related("page__directory")
        for r in redirects:
            slug_map[r.old_slug] = r.page

    # 1) Replace [text](#slug) — known slugs get resolved, unknown left as-is
    def replace_md_link(match):
        text, slug = match.group(1), match.group(2)
        if slug in slug_map:
            return f"[{text}]({slug_map[slug].get_absolute_url()})"
        return match.group(0)

    content = _MD_LINK_WIKI_RE.sub(replace_md_link, content)

    # 2) Replace [ref]: #slug — known slugs get resolved, unknown left as-is
    def replace_ref_link(match):
        prefix, slug = match.group(1), match.group(2)
        if slug in slug_map:
            return f"{prefix}{slug_map[slug].get_absolute_url()}"
        return match.group(0)

    content = _REF_LINK_WIKI_RE.sub(replace_ref_link, content)

    # 3) Replace standalone #slug — known → link, unknown → red text
    def replace_link(match):
        slug = match.group(1)
        # Skip if this #slug sits inside a reference-style definition
        # ([ref]: #slug) — step 2 already handled those.
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        line_end = match.string.find("\n", match.end())
        if line_end == -1:
            line_end = len(match.string)
        line = match.string[line_start:line_end]
        if _REF_LINK_WIKI_RE.match(line):
            return match.group(0)
        if slug in slug_map:
            page = slug_map[slug]
            url = page.get_absolute_url()
            return f"[{page.title}]({url})"
        else:
            return f'<span class="text-red-500 dark:text-red-400" title="Page not found">#{slug}</span>'

    return WIKI_LINK_RE.sub(replace_link, content)


def extract_all_wiki_slugs(content):
    """Extract page slugs from all wiki link syntaxes in raw content.

    Finds slugs from:
    - Standalone #slug references
    - [text](#slug) markdown links
    - [ref]: #slug reference definitions
    """
    slugs = set(WIKI_LINK_RE.findall(content))
    slugs |= {m.group(2) for m in _MD_LINK_WIKI_RE.finditer(content)}
    slugs |= {m.group(2) for m in _REF_LINK_WIKI_RE.finditer(content)}
    return slugs


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
_ALERT_MARKER_STRIP_RE = re.compile(
    r"\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", re.IGNORECASE
)
_BUTTON_SUFFIX_STRIP_RE = re.compile(r"\{button(?:-(outline|danger))?\}")
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
    text = _ALERT_MARKER_STRIP_RE.sub("", text)
    text = _BUTTON_SUFFIX_STRIP_RE.sub("", text)
    text = _UL_RE.sub("", text)
    text = _OL_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


_INTERNAL_HREF_RE = re.compile(r'<a\s+href="((?:https?://[^"]*)?/c/[^"]+)"')


def _add_nofollow_to_non_public_links(html):
    """Add rel="nofollow" to internal links pointing to non-public pages.

    Finds <a href="/c/..."> tags, extracts slugs, batch-checks their
    effective visibility, and adds rel="nofollow" for non-public targets.
    """
    # Inline import to avoid circular dependency (pages/models ↔ lib/markdown)
    from wiki.pages.models import Page

    hrefs = _INTERNAL_HREF_RE.findall(html)
    if not hrefs:
        return html

    # Extract slugs from internal URLs (last path segment after /c/)
    slug_by_href = {}
    for href in hrefs:
        # For full URLs, extract just the path portion
        if href.startswith("http"):
            path = urlparse(href).path
        else:
            path = href
        path = path.rstrip("/")
        slug = path.rsplit("/", 1)[-1]
        if slug:
            slug_by_href[href] = slug

    if not slug_by_href:
        return html

    # Batch-load pages for all referenced slugs
    unique_slugs = set(slug_by_href.values())
    pages = Page.objects.filter(slug__in=unique_slugs).select_related(
        "directory", "directory__parent"
    )
    page_map = {p.slug: p for p in pages}

    # Determine which hrefs need nofollow
    nofollow_hrefs = set()
    for href, slug in slug_by_href.items():
        page = page_map.get(slug)
        if not page:
            continue
        effective_vis, _ = resolve_effective_value(page, "visibility")
        if effective_vis != "public":
            nofollow_hrefs.add(href)

    if not nofollow_hrefs:
        return html

    def add_rel(match):
        href = match.group(1)
        if href in nofollow_hrefs:
            return f'<a rel="nofollow" href="{href}"'
        return match.group(0)

    return _INTERNAL_HREF_RE.sub(add_rel, html)


def _convert_alerts(html):
    """Convert GitHub-style alert blockquotes to styled divs.

    Transforms blockquotes starting with [!NOTE], [!TIP], [!IMPORTANT],
    [!WARNING], or [!CAUTION] into styled alert containers. Runs after
    sanitization so injected HTML is already stripped.
    """

    def replace_alert(match):
        alert_type = match.group(1).upper()
        css_class = alert_type.lower()
        title = _ALERT_TITLES[alert_type]
        content = match.group(2).strip()
        # Ensure content starts with a <p> tag (it was mid-paragraph)
        if not content.startswith("<p>"):
            content = "<p>" + content
        return (
            f'<div class="markdown-alert markdown-alert-{css_class}">'
            f'<p class="markdown-alert-title">{title}</p>'
            f"\n{content}"
            f"\n</div>"
        )

    return _ALERT_BLOCKQUOTE_RE.sub(replace_alert, html)


def _convert_button_links(html):
    """Convert links with {button} suffix to button-styled links.

    Transforms [text](url){button} into a link with btn btn-primary classes.
    Also supports {button-outline}, {button-danger}, {button-ghost}. Runs
    after sanitization so the class attribute is safely added.
    """

    def replace_button(match):
        tag_attrs = match.group(1)
        text = match.group(2)
        variant = match.group(3) or "primary"
        return f'{tag_attrs} class="btn btn-{variant}">{text}</a>'

    return _BUTTON_LINK_RE.sub(replace_button, html)


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
            "link-patterns",
        ],
        link_patterns=[(_AUTOLINK_RE, r"\1")],
    )
    toc = getattr(html, "toc_html", "")
    sanitized = _sanitize(str(html))
    processed = _add_nofollow_to_non_public_links(sanitized)
    processed = _convert_alerts(processed)
    processed = _convert_button_links(processed)
    result = MarkdownResult(processed)
    result.toc_html = _sanitize(toc) if toc else ""
    return result
