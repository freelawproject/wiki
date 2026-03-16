from collections import defaultdict

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse

from wiki.lib.inheritance import resolve_all_directory_settings
from wiki.lib.seo import extract_description
from wiki.lib.sitemap import (
    _effectively_public_directory_ids,
    _llms_directory_map,
)
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

    Pages are included based on their effective in_llms_txt and
    visibility values (resolved through the inheritance chain).
    """
    base = settings.BASE_URL
    dir_map = _llms_directory_map()  # dir_id -> effective llms status
    public_dir_ids = _effectively_public_directory_ids()

    # Resolve effective llms.txt status for directory-level inheritance
    llms_resolved = resolve_all_directory_settings("in_llms_txt")

    # Directory IDs where effective llms status is not "exclude"
    non_excluded_dir_ids = {
        dir_id
        for dir_id, (eff_value, _, _) in llms_resolved.items()
        if eff_value != "exclude" and dir_id in public_dir_ids
    }

    # Fetch pages that are effectively public and not excluded from llms.txt
    # We need to handle both explicit and inherited values
    pages = (
        Page.objects.filter(
            # Effectively public
            Q(visibility="public")
            | Q(visibility="inherit", directory_id__in=public_dir_ids)
        )
        .exclude(in_llms_txt="exclude")  # Explicitly excluded pages
        .filter(
            Q(directory__isnull=True)
            | Q(directory_id__in=non_excluded_dir_ids)
        )
        .select_related("directory")
        .order_by("directory__path", "title")
    )

    by_dir = defaultdict(list)
    optional_pages = []
    for page in pages:
        dir_id = page.directory_id

        # Determine effective llms status for this page
        if page.in_llms_txt != "inherit":
            effective = page.in_llms_txt
        elif dir_id:
            effective = dir_map.get(dir_id, "exclude")
        else:
            effective = "exclude"  # Root-level page with "inherit" = default

        if effective == "exclude":
            continue

        if effective == "optional":
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
