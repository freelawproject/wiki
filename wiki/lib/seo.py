"""SEO utilities: description extraction, JSON-LD breadcrumbs, and Article schema."""

import json

from wiki.lib.markdown import strip_markdown


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
    return json.dumps(schema)


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
    return json.dumps(schema)
