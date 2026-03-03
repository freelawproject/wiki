from datetime import date

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render

from .search import SORT_OPTIONS, search_pages
from .search_parser import parse_query


def _parse_url_date(value):
    """Parse a YYYY-MM-DD string from a URL param, or return None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _compute_facets(qs):
    """Compute directory and visibility facets from the queryset."""
    directory_facets = (
        qs.exclude(directory__isnull=True)
        .values("directory__path", "directory__title")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    visibility_facets = (
        qs.values("visibility").annotate(count=Count("id")).order_by("-count")
    )
    return {
        "directories": list(directory_facets),
        "visibility": list(visibility_facets),
    }


def _pagination_params(request):
    """Build query string with all params except 'page'."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def search_view(request):
    """Full-text search across wiki pages."""
    raw_query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "relevance")
    page_num = request.GET.get("page", "1")

    if not raw_query:
        return render(
            request,
            "pages/search.html",
            {
                "query": "",
                "results": [],
                "sort_options": SORT_OPTIONS,
                "current_sort": sort,
            },
        )

    parsed = parse_query(raw_query)

    # Merge URL-driven filters (from facet sidebar clicks)
    url_dir = request.GET.get("dir", "").strip()
    if url_dir and url_dir not in parsed.directories:
        parsed.directories.append(url_dir)

    url_visibility = request.GET.get("visibility", "").strip()
    if url_visibility and not parsed.visibility:
        parsed.visibility = url_visibility

    url_after = _parse_url_date(request.GET.get("after", "").strip())
    if url_after and not parsed.after_date:
        parsed.after_date = url_after

    url_before = _parse_url_date(request.GET.get("before", "").strip())
    if url_before and not parsed.before_date:
        parsed.before_date = url_before

    qs, total_count = search_pages(parsed, user=request.user, sort=sort)

    # Compute facets from the full queryset (before pagination)
    facets = _compute_facets(qs)

    paginator = Paginator(qs, settings.SEARCH_RESULTS_PER_PAGE)
    try:
        page_num = int(page_num)
    except (ValueError, TypeError):
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Active filters for removable chips
    active_filters = []
    if url_dir:
        active_filters.append(
            {"type": "dir", "label": f"Dir: {url_dir}", "value": url_dir}
        )
    if url_visibility:
        active_filters.append(
            {
                "type": "visibility",
                "label": f"Visibility: {url_visibility}",
                "value": url_visibility,
            }
        )
    if url_after:
        active_filters.append(
            {
                "type": "after",
                "label": f"After: {url_after.isoformat()}",
                "value": url_after.isoformat(),
            }
        )
    if url_before:
        active_filters.append(
            {
                "type": "before",
                "label": f"Before: {url_before.isoformat()}",
                "value": url_before.isoformat(),
            }
        )

    return render(
        request,
        "pages/search.html",
        {
            "query": raw_query,
            "results": page_obj,
            "page_obj": page_obj,
            "total_count": total_count,
            "facets": facets,
            "sort_options": SORT_OPTIONS,
            "current_sort": sort,
            "active_filters": active_filters,
            "pagination_params": _pagination_params(request),
        },
    )
