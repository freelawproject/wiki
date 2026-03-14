from collections import defaultdict

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse

from wiki.lib.seo import extract_description
from wiki.lib.sitemap import _public_directory_ids
from wiki.pages.models import Page


def ratelimited(request, exception=None):
    """Return a 429 Too Many Requests response."""
    html = render_to_string("429.html", request=request)
    return HttpResponse(html, status=429)


def robots_txt(request):
    """Serve robots.txt with crawl directives."""
    sitemap_url = f"{settings.BASE_URL}{reverse('django.contrib.sitemaps.views.sitemap')}"
    lines = [
        "User-agent: *",
        "Allow: /c/",
        "Allow: /llms.txt",
        "",
        # Admin and internal paths
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /u/",
        "Disallow: /search/",
        "Disallow: /files/",
        "Disallow: /unsubscribe/",
        "Disallow: /activity/",
        "",
        # Page action URLs (edit, delete, history, etc.)
        "Disallow: /c/*/edit/",
        "Disallow: /c/*/move/",
        "Disallow: /c/*/delete/",
        "Disallow: /c/*/history/",
        "Disallow: /c/*/backlinks/",
        "Disallow: /c/*/diff/",
        "Disallow: /c/*/revert/",
        "Disallow: /c/*/permissions/",
        "Disallow: /c/*/subscribe/",
        "Disallow: /c/*/pin/",
        "",
        # Directory action URLs
        "Disallow: /c/*/new/",
        "Disallow: /c/*/new-dir/",
        "Disallow: /c/*/edit-dir/",
        "Disallow: /c/*/move-dir/",
        "Disallow: /c/*/delete-dir/",
        "Disallow: /c/*/history-dir/",
        "Disallow: /c/*/diff-dir/",
        "Disallow: /c/*/revert-dir/",
        "Disallow: /c/*/permissions-dir/",
        "Disallow: /c/*/apply-permissions-dir/",
        "Disallow: /c/*/subscribe-dir/",
        "",
        # Root-level directory actions
        "Disallow: /c/new/",
        "Disallow: /c/new-dir/",
        "Disallow: /c/edit-dir/",
        "Disallow: /c/history-dir/",
        "Disallow: /c/diff-dir/",
        "Disallow: /c/permissions-dir/",
        "Disallow: /c/apply-permissions-dir/",
        "Disallow: /c/subscribe-dir/",
        "",
        # Comments and proposals
        "Disallow: /c/*/comments/",
        "Disallow: /c/*/proposals/",
        "Disallow: /c/*/feedback/",
        "",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def _llms_txt_entry(page, base_url):
    """Format a single llms.txt entry line."""
    desc = page.seo_description or extract_description(
        page.content, max_length=100
    )
    md_url = f"{base_url}{page.get_absolute_url()}.md"
    entry = f"- [{page.title}]({md_url})"
    if desc:
        entry += f": {desc}"
    return entry


def llms_txt(request):
    """Serve llms.txt — an index of public wiki pages for LLM crawlers.

    Links point to the .md (raw markdown) endpoint for each page.
    Format follows https://llmstxt.org/ spec.
    """
    base = settings.BASE_URL
    public_dir_ids = _public_directory_ids()

    pages = (
        Page.objects.filter(visibility=Page.Visibility.PUBLIC)
        .filter(Q(directory__isnull=True) | Q(directory_id__in=public_dir_ids))
        .select_related("directory")
        .order_by("directory__path", "title")
    )

    # Group pages by directory, separating help pages into Optional
    by_dir = defaultdict(list)
    optional_pages = []
    for page in pages:
        dir_path = page.directory.path if page.directory else ""
        if dir_path == "help" or dir_path.startswith("help/"):
            optional_pages.append(page)
        else:
            dir_title = page.directory.title if page.directory else "Root"
            by_dir[dir_title].append(page)

    lines = [
        "# FLP Wiki",
        "",
        "> Free Law Project's wiki covering legal technology, "
        "open legal data, and organizational knowledge.",
        "",
    ]

    for dir_title, dir_pages in by_dir.items():
        lines.append(f"## {dir_title}")
        lines.append("")
        for page in dir_pages:
            lines.append(_llms_txt_entry(page, base))
        lines.append("")

    if optional_pages:
        lines.append("## Optional")
        lines.append("")
        for page in optional_pages:
            lines.append(_llms_txt_entry(page, base))
        lines.append("")

    response = HttpResponse("\n".join(lines), content_type="text/plain")
    response["X-Robots-Tag"] = "noindex"
    return response
