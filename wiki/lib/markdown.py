"""Markdown rendering with wiki link resolution.

Wiki links use the syntax #page-slug. During rendering, these are
resolved to actual page URLs or shown as red links for missing pages.
"""

import re

import markdown2

WIKI_LINK_RE = re.compile(r"(?<!\w)#([a-z0-9]+(?:-[a-z0-9]+)*)")


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


def render_markdown(content):
    """Render markdown content to HTML with wiki link resolution and TOC."""
    content = resolve_wiki_links(content)
    return markdown2.markdown(
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
