"""SEO utilities: description extraction and JSON-LD breadcrumbs."""

import json
import re


def extract_description(markdown: str, max_length: int = 160) -> str:
    """Extract a plain-text description from markdown content.

    Strips headings, code blocks, links, emphasis, images, and HTML
    tags, then returns the first ``max_length`` characters of the
    remaining text.
    """
    if not markdown:
        return ""

    text = markdown

    # Remove fenced code blocks (``` ... ```)
    text = re.sub(r"```[\s\S]*?```", "", text)

    # Remove inline code (`...`)
    text = re.sub(r"`[^`]+`", "", text)

    # Remove headings (# ... )
    text = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE)

    # Remove images (![alt](url))
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)

    # Convert links [text](url) to just text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)

    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}|_{1,3}", "", text)

    # Remove strikethrough
    text = re.sub(r"~~", "", text)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Remove blockquote markers
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)

    # Remove list markers
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

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
