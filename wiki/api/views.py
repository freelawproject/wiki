"""Read-only JSON API for machine clients such as the CourtListener MCP
server. Anyone sees public pages; a CourtListener bearer token sees what
that account's email can see (see ``auth``).

A page's ``content`` is the Markdown readers see by default: data
placeholders filled and wiki links resolved for the caller, so its links are
ordinary ``/c/...`` paths. ``?raw=true`` returns the stored source instead,
wiki syntax and all."""

from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils.html import strip_tags
from django.views.decorators.http import require_GET

from wiki.api.auth import bearer_auth
from wiki.lib.data_source import page_content_with_data
from wiki.lib.markdown import resolve_wiki_links
from wiki.lib.page_utils import page_at_path
from wiki.lib.permissions import can_view_page, viewable_pages_q
from wiki.lib.ratelimiter import ratelimit_api
from wiki.lib.seo import extract_description
from wiki.pages.models import Page
from wiki.pages.search import search_pages
from wiki.pages.search_parser import parse_query


def _summary(page):
    return {
        "path": page.content_path,
        "title": page.title,
        "description": page.seo_description
        or extract_description(page.content),
        "updated_at": page.updated_at,
    }


def _paginated(request, queryset, per_page, key, item):
    """The ``?page=`` of ``queryset`` under ``key``, ``item`` applied to each."""
    page = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    return JsonResponse(
        {
            "total": page.paginator.count,
            "page": page.number,
            "next_page": page.next_page_number() if page.has_next() else None,
            key: [item(p) for p in page],
        }
    )


@ratelimit_api
@require_GET
@bearer_auth
def page_list(request):
    pages = (
        Page.objects.filter(viewable_pages_q(request.user))
        .select_related("directory")
        .order_by("directory__path", "title", "pk")
        .distinct()
    )
    return _paginated(
        request, pages, settings.PAGE_LIST_RESULTS_PER_PAGE, "pages", _summary
    )


@ratelimit_api
@require_GET
@bearer_auth
def page_search(request):
    pages = search_pages(parse_query(request.GET.get("q", "")), request.user)
    return _paginated(
        request,
        pages,
        settings.SEARCH_RESULTS_PER_PAGE,
        "results",
        lambda p: {**_summary(p), "snippet": strip_tags(p.headline)},
    )


@ratelimit_api
@require_GET
@bearer_auth
def page_detail(request, path):
    page = page_at_path(path.strip("/"))
    if page is None or not can_view_page(request.user, page):
        return JsonResponse({"error": "not_found"}, status=404)
    if request.GET.get("raw", "").lower() in ("1", "true"):
        content = page.content
    else:
        # A link to a page the caller can't see stays as written, without
        # the web's not-found HTML.
        content = resolve_wiki_links(
            page_content_with_data(page),
            viewer=request.user,
            mark_missing=False,
        )
    return JsonResponse({**_summary(page), "content": content})
