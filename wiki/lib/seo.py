"""SEO utilities: description extraction, JSON-LD breadcrumbs, and Article schema."""

import json

from wiki.lib.markdown import strip_markdown

# json.dumps does not escape "<", ">" or "&", so a "</script>" substring in any
# user-controlled value (e.g. a directory title) would close the surrounding
# <script type="application/ld+json"> element early and allow stored XSS.
# Django's json_script() escapes these but hardcodes type="application/json",
# which crawlers do not parse as JSON-LD, so we mirror its escape set here.
_JSONLD_ESCAPES = {ord(c): chr(92) + f"u{ord(c):04x}" for c in "<>&"}


def _dump_jsonld(schema: dict) -> str:
    """Serialize a schema dict to a string safe for <script> embedding."""
    return json.dumps(schema).translate(_JSONLD_ESCAPES)


def extract_description(markdown: str, max_length: int = 160) -> str:
    """Extract a plain-text description from markdown content.

    Strips all markdown formatting, then returns the first
    ``max_length`` characters of the remaining text.
    """
    text = strip_markdown(markdown)
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    # Truncate at a word boundary
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;:!?") + "..."


def build_breadcrumbs_jsonld(
    breadcrumbs: list[tuple[str, str]], base_url: str
) -> str:
    """Build a JSON-LD BreadcrumbList from (title, relative_url) tuples.

    Returns a JSON string suitable for embedding in a <script> tag.
    """
    items = []
    for position, (name, url) in enumerate(breadcrumbs, start=1):
        absolute_url = url if url.startswith("http") else f"{base_url}{url}"
        items.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": name,
                "item": absolute_url,
            }
        )

    schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }
    return _dump_jsonld(schema)


def build_collection_jsonld(directory, description, base_url):
    """Build a JSON-LD CollectionPage schema for a wiki directory.

    Directories are listing pages, so CollectionPage is a better fit than
    Article. Returns a JSON string suitable for embedding in a <script> tag.
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": directory.title,
        "description": description,
        "url": f"{base_url}{directory.get_absolute_url()}",
        "dateModified": directory.updated_at.isoformat(),
        "publisher": {
            "@type": "Organization",
            "name": "Free Law Project",
            "url": "https://free.law",
        },
    }
    return _dump_jsonld(schema)


def build_article_jsonld(page, description, base_url):
    """Build a JSON-LD Article schema for a wiki page.

    Returns a JSON string suitable for embedding in a <script> tag.
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": page.title,
        "description": description,
        "url": f"{base_url}{page.get_absolute_url()}",
        "datePublished": page.created_at.isoformat(),
        "dateModified": page.updated_at.isoformat(),
        "publisher": {
            "@type": "Organization",
            "name": "Free Law Project",
            "url": "https://free.law",
        },
    }
    return _dump_jsonld(schema)
