"""Markdown rendering with wiki link resolution.

Wiki links use the syntax #page-slug. During rendering, these are
resolved to actual page URLs or shown as red links for missing pages.
"""

import re
from urllib.parse import urlparse

import markdown2
import nh3
from django.conf import settings
from django.db.models import Q
from django.urls import Resolver404, resolve

from wiki.directories.models import Directory
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
    r'(<a\s[^>]*href="[^"]*"[^>]*)>((?:(?!</a>).)*)</a>'
    r"\s*\{button(?:-(outline|danger))?\}",
)

_SLUG_CHARS = r"[a-z0-9]+(?:-[a-z0-9]+)*"

# Captures a wiki-link target: an optional directory path, the page slug,
# and an optional #fragment anchor. Used as a building block in the three
# anchored regexes below (standalone, md-link, ref-link).
#   #slug                      → dir=None,     slug=slug,     fragment=None
#   #hr/onboarding             → dir="hr",     slug="onboarding"
#   #hr/docs/ci#setup          → dir="hr/docs", slug="ci", fragment="setup"
_WIKI_LINK_TARGET_RE = (
    rf"(?:(?P<dir>{_SLUG_CHARS}(?:/{_SLUG_CHARS})*)/)?"
    rf"(?P<slug>{_SLUG_CHARS})"
    rf"(?:#(?P<fragment>{_SLUG_CHARS}))?"
)

WIKI_LINK_RE = re.compile(r"(?<!\w)(?<!\()(?<!/)#" + _WIKI_LINK_TARGET_RE)

_MD_LINK_WIKI_RE = re.compile(
    r"\[(?P<text>[^\]]+)\]\(#" + _WIKI_LINK_TARGET_RE + r"\)"
)

_REF_LINK_WIKI_RE = re.compile(
    r"^(?P<prefix>\[[^\]]+\]:\s*)#" + _WIKI_LINK_TARGET_RE + r"\s*$",
    re.MULTILINE,
)

# Fenced code blocks and inline backticks — wiki link extraction and
# resolution must skip these so documentation examples aren't rewritten.
_CODE_REGIONS_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")

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


def _code_region_ranges(content):
    """Return (start, end) spans for fenced code blocks and inline backticks."""
    return [(m.start(), m.end()) for m in _CODE_REGIONS_RE.finditer(content)]


def _in_code_region(pos, ranges):
    return any(start <= pos < end for start, end in ranges)


def extract_references_from_internal_urls(content):
    """Extract (dir_path, slug) references from internal wiki URLs.

    Finds URLs like /c/dir/slug or {BASE_URL}/c/dir/slug and returns a
    set of (directory_path, slug) tuples. URL #fragments and code-block
    regions are skipped.
    """
    base_url = getattr(settings, "BASE_URL", "")
    base_host = urlparse(base_url).hostname or ""
    code_ranges = _code_region_ranges(content)
    refs = set()
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
    for match in _INTERNAL_URL_RE.finditer(content):
        if _in_code_region(match.start(), code_ranges):
            continue
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
        # Drop #fragment before segment extraction
        path = path.split("#", 1)[0]
        path = path.rstrip("/")
        if not path.startswith("/c/"):
            continue
        content_path = path[3:]  # remove "/c/"
        if any(content_path.endswith(s) for s in action_suffixes):
            continue
        if "/" in content_path:
            dir_path, slug = content_path.rsplit("/", 1)
        else:
            dir_path, slug = "", content_path
        if slug:
            refs.add((dir_path, slug))
    return refs


def extract_slugs_from_internal_urls(content):
    """Return bare slugs referenced by internal wiki URLs.

    Convenience wrapper over ``extract_references_from_internal_urls``.
    """
    return {
        slug for _dir, slug in extract_references_from_internal_urls(content)
    }


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
    "kbd",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "input": {"type", "checked", "disabled"},
    "p": {"class"},
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


def _iter_references(content, code_ranges):
    """Yield (dir_path, slug) tuples for every wiki link across all syntaxes.

    Walks all three regexes (standalone, md-link, ref-link). Matches inside
    fenced code blocks or inline backticks are skipped. ``dir_path`` is the
    full directory path, or ``""`` for bare references.
    """
    for regex in (WIKI_LINK_RE, _MD_LINK_WIKI_RE, _REF_LINK_WIKI_RE):
        for m in regex.finditer(content):
            if _in_code_region(m.start(), code_ranges):
                continue
            yield m.group("dir") or "", m.group("slug")


def resolve_references(references, exclude_pk=None):
    """Resolve a set of ``(dir_path, slug)`` tuples to ``Page`` objects.

    Returns a dict ``{(dir_path, slug): Page}``. Qualified refs (non-empty
    ``dir_path``) match on ``(directory.path, slug)`` exactly. Bare refs
    (``dir_path == ""``) use a ``created_at`` tiebreaker — the oldest
    active page with that slug wins, across any directory. ``SlugRedirect``
    is consulted as a fallback for anything that didn't match directly.

    Shared by ``resolve_wiki_links`` (link rendering) and
    ``Page._update_page_links`` (PageLink graph maintenance), so both
    layers agree on what each textual reference points to.

    If ``exclude_pk`` is given, the matching page is skipped — useful for
    link-tracking where self-references shouldn't be recorded.
    """
    # Inline import to avoid circular dependency (pages/models ↔ lib/markdown)
    from wiki.pages.models import Page, SlugRedirect

    qualified_refs = {(d, s) for d, s in references if d}
    bare_slugs = {s for d, s in references if not d}

    page_qs = Page.objects.all()
    redirect_qs = SlugRedirect.objects.all()
    if exclude_pk is not None:
        page_qs = page_qs.exclude(pk=exclude_pk)
        redirect_qs = redirect_qs.exclude(page_id=exclude_pk)

    resolved = {}

    if qualified_refs:
        q = Q()
        for d, s in qualified_refs:
            q |= Q(directory__path=d, slug=s)
        for p in page_qs.filter(q).select_related("directory"):
            resolved[(p.directory.path, p.slug)] = p
        missing = qualified_refs - set(resolved.keys())
        if missing:
            rq = Q()
            for d, s in missing:
                rq |= Q(directory__path=d, old_slug=s)
            for r in redirect_qs.filter(rq).select_related(
                "page__directory", "directory"
            ):
                resolved[(r.directory.path, r.old_slug)] = r.page

    if bare_slugs:
        seen = set()
        for p in (
            page_qs.filter(slug__in=bare_slugs)
            .order_by("slug", "created_at")
            .select_related("directory")
        ):
            if p.slug not in seen:
                seen.add(p.slug)
                resolved[("", p.slug)] = p
        missing = bare_slugs - seen
        if missing:
            for r in (
                redirect_qs.filter(old_slug__in=missing)
                .order_by("old_slug", "page__created_at")
                .select_related("page__directory")
            ):
                if r.old_slug not in seen:
                    seen.add(r.old_slug)
                    resolved[("", r.old_slug)] = r.page

    return resolved


def _build_link_resolver(content, code_ranges):
    """Return ``resolve(dir_path, slug) -> Page | None`` for ``content``.

    Thin wrapper around ``resolve_references`` that extracts the refs
    from ``content`` first.
    """
    references = set(_iter_references(content, code_ranges))
    resolved = resolve_references(references)

    def resolve(dir_path, slug):
        return resolved.get((dir_path, slug))

    return resolve


def _append_fragment(url, fragment):
    return f"{url}#{fragment}" if fragment else url


def resolve_wiki_links(content):
    """Replace #slug and #dir/slug references with proper markdown links.

    Handles three syntaxes:
    - Standalone: #slug → [Title](/dir/path/slug)
    - Inline link: [text](#slug) → [text](/dir/path/slug)
    - Reference link: [ref]: #slug → [ref]: /dir/path/slug

    Qualified (#dir/slug) forms resolve unambiguously via directory path.
    Bare (#slug) forms resolve via the oldest matching page (legacy
    shorthand). Known refs become links; unknown standalone refs render
    as red text; unknown md/ref refs are left as-is (may be heading
    anchors).
    """
    code_ranges = _code_region_ranges(content)
    # Bail fast if there are no wiki-link-shaped tokens at all
    if not any(True for _ in _iter_references(content, code_ranges)):
        return content

    resolve = _build_link_resolver(content, code_ranges)

    def replace_md_link(match):
        if _in_code_region(match.start(), code_ranges):
            return match.group(0)
        text = match.group("text")
        dir_path = match.group("dir") or ""
        slug = match.group("slug")
        fragment = match.group("fragment")
        page = resolve(dir_path, slug)
        if page is not None:
            url = _append_fragment(page.get_absolute_url(), fragment)
            return f"[{text}]({url})"
        return match.group(0)

    content = _MD_LINK_WIKI_RE.sub(replace_md_link, content)
    # Each sub can change content length, so code-region offsets shift —
    # recompute before the next callback that consults them.
    code_ranges_after_md = _code_region_ranges(content)

    def replace_ref_link(match):
        if _in_code_region(match.start(), code_ranges_after_md):
            return match.group(0)
        prefix = match.group("prefix")
        dir_path = match.group("dir") or ""
        slug = match.group("slug")
        fragment = match.group("fragment")
        page = resolve(dir_path, slug)
        if page is not None:
            url = _append_fragment(page.get_absolute_url(), fragment)
            return f"{prefix}{url}"
        return match.group(0)

    content = _REF_LINK_WIKI_RE.sub(replace_ref_link, content)
    code_ranges_after_ref = _code_region_ranges(content)

    def replace_link(match):
        if _in_code_region(match.start(), code_ranges_after_ref):
            return match.group(0)
        dir_path = match.group("dir") or ""
        slug = match.group("slug")
        fragment = match.group("fragment")
        # Skip if this sits inside a reference-style definition — replace_ref_link
        # already handled those.
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        line_end = match.string.find("\n", match.end())
        if line_end == -1:
            line_end = len(match.string)
        line = match.string[line_start:line_end]
        if _REF_LINK_WIKI_RE.match(line):
            return match.group(0)
        page = resolve(dir_path, slug)
        if page is not None:
            url = _append_fragment(page.get_absolute_url(), fragment)
            return f"[{page.title}]({url})"
        return (
            f'<span class="text-red-500 dark:text-red-400" '
            f'title="Page not found">{match.group(0)}</span>'
        )

    return WIKI_LINK_RE.sub(replace_link, content)


def extract_all_wiki_references(content):
    """Extract (dir_path, slug) references from all wiki link syntaxes.

    Finds references from:
    - Standalone #slug and #dir/slug
    - [text](#slug) / [text](#dir/slug)
    - [ref]: #slug / [ref]: #dir/slug

    Returns a set of (dir_path, slug) tuples. dir_path is "" for bare
    references. Code-block and inline-backtick regions are skipped.
    """
    code_ranges = _code_region_ranges(content)
    return set(_iter_references(content, code_ranges))


def extract_all_wiki_slugs(content):
    """Return the set of bare slugs referenced by any wiki link syntax.

    This is a convenience wrapper over ``extract_all_wiki_references``
    that drops the directory component — useful when callers want a
    coarse "does this page mention slug X anywhere" check. For link
    resolution, prefer ``extract_all_wiki_references``.
    """
    return {slug for _dir, slug in extract_all_wiki_references(content)}


def qualify_bare_links(content, target_slug, qualified_path):
    """Rewrite bare ``#<target_slug>`` references to ``#<qualified_path>``.

    Used when a save introduces a slug collision: links elsewhere in the
    wiki that used the bare form to point at a now-ambiguous slug get
    rewritten in-place to their qualified form. Fragments are preserved.
    ``qualified_path`` is the full directory-plus-slug path (e.g.,
    ``"hr/overview"``). Rewrites happen in standalone ``#slug``,
    ``[text](#slug)``, and ``[ref]: #slug`` forms; matches inside code
    regions are skipped.
    """
    code_ranges = _code_region_ranges(content)

    def _should_rewrite(match):
        if _in_code_region(match.start(), code_ranges):
            return False
        if match.group("dir"):
            return False
        return match.group("slug") == target_slug

    def _new_ref(match):
        fragment = match.group("fragment")
        new = f"#{qualified_path}"
        if fragment:
            new += f"#{fragment}"
        return new

    # Rewrite reference-style definitions first so the standalone pass
    # doesn't mistake them for bare references.
    def replace_ref(match):
        if not _should_rewrite(match):
            return match.group(0)
        return f"{match.group('prefix')}{_new_ref(match)}"

    content = _REF_LINK_WIKI_RE.sub(replace_ref, content)
    code_ranges = _code_region_ranges(content)

    def replace_md(match):
        if not _should_rewrite(match):
            return match.group(0)
        return f"[{match.group('text')}]({_new_ref(match)})"

    content = _MD_LINK_WIKI_RE.sub(replace_md, content)
    code_ranges = _code_region_ranges(content)

    def replace_standalone(match):
        if not _should_rewrite(match):
            return match.group(0)
        # Skip lines that are ref-style definitions (handled above).
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        line_end = match.string.find("\n", match.end())
        if line_end == -1:
            line_end = len(match.string)
        if _REF_LINK_WIKI_RE.match(match.string[line_start:line_end]):
            return match.group(0)
        return _new_ref(match)

    return WIKI_LINK_RE.sub(replace_standalone, content)


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
    """Add rel="nofollow" to internal links pointing to non-public content.

    Finds <a href="/c/..."> tags, uses Django's URL resolver to extract
    content paths, then batch-checks pages and directories. Adds
    rel="nofollow" when the target is non-public or doesn't exist
    (broken link → 404 for crawlers).
    """
    # Inline import to avoid circular dependency (pages/models ↔ lib/markdown)
    from wiki.pages.models import Page

    hrefs = _INTERNAL_HREF_RE.findall(html)
    if not hrefs:
        return html

    # Use Django's URL resolver to extract content paths from hrefs
    path_by_href = {}
    slug_set = set()
    for href in hrefs:
        url_path = urlparse(href).path
        try:
            match = resolve(url_path)
        except Resolver404:
            continue
        # Only process the content catch-all; action URLs (edit, move,
        # etc.) are already blocked by robots.txt.
        if match.url_name != "resolve_path":
            continue
        content_path = match.kwargs.get("path", "")
        if not content_path:
            continue
        path_by_href[href] = content_path
        slug_set.add(content_path.rsplit("/", 1)[-1])

    if not path_by_href:
        return html

    # Batch-load pages by slug, then index by content_path
    pages = Page.objects.filter(slug__in=slug_set).select_related(
        "directory", "directory__parent", "directory__parent__parent"
    )
    page_by_path = {p.content_path: p for p in pages}

    # For paths that didn't match a page, check directories
    unique_paths = set(path_by_href.values())
    unmatched = unique_paths - set(page_by_path.keys())
    dir_by_path = {}
    if unmatched:
        dirs = Directory.objects.filter(path__in=unmatched).select_related(
            "parent", "parent__parent", "parent__parent__parent"
        )
        dir_by_path = {d.path: d for d in dirs}

    # Determine which hrefs need nofollow
    nofollow_hrefs = set()
    for href, content_path in path_by_href.items():
        page = page_by_path.get(content_path)
        if page:
            effective_vis, _ = resolve_effective_value(page, "visibility")
            if effective_vis != "public":
                nofollow_hrefs.add(href)
            continue

        directory = dir_by_path.get(content_path)
        if directory:
            effective_vis, _ = resolve_effective_value(directory, "visibility")
            if effective_vis != "public":
                nofollow_hrefs.add(href)
            continue

        # Neither page nor directory — broken link leads to 404
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
