"""Read-only JSON API for machine clients such as the CourtListener MCP
server. Anyone sees public pages; a CourtListener bearer token sees what
that account's email can see (see ``auth``)."""

from django.conf import settings
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils.html import strip_tags
from django.views.decorators.http import require_GET

from wiki.api.auth import bearer_auth
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
        .order_by("directory__path", "title")
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
    return JsonResponse({**_summary(page), "content": page.content})
