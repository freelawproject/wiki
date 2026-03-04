import json
from datetime import date

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render

from wiki.directories.models import Directory

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


def _build_initial_chips(parsed):
    """Build chip data from parsed query for the search input UI."""
    chips = []
    for d in parsed.directories:
        dir_obj = Directory.objects.filter(path=d).first()
        chips.append(
            {
                "key": "in",
                "value": d,
                "label": dir_obj.title if dir_obj else d,
            }
        )
    for o in parsed.owners:
        chips.append({"key": "owner", "value": o})
    for t in parsed.title_terms:
        chips.append({"key": "title", "value": t})
    for c in parsed.content_terms:
        chips.append({"key": "content", "value": c})
    if parsed.visibility:
        chips.append({"key": "is", "value": parsed.visibility})
    if parsed.before_date:
        chips.append(
            {"key": "before", "value": parsed.before_date.isoformat()}
        )
    if parsed.after_date:
        chips.append({"key": "after", "value": parsed.after_date.isoformat()})
    return chips


def _build_query_text(parsed):
    """Reconstruct the free-text portion of the query."""
    parts = []
    if parsed.text:
        parts.append(parsed.text)
    for phrase in parsed.phrases:
        parts.append('"' + phrase + '"')
    for excl in parsed.excluded:
        parts.append("-" + excl)
    return " ".join(parts)


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

    # Build chip data and free-text for the search input UI
    initial_chips = _build_initial_chips(parsed)
    initial_chips_json = json.dumps(initial_chips)
    search_query_text = _build_query_text(parsed)

    # Dir context for the search bar dropdown suggestion
    search_dir_path = ""
    search_dir_title = ""
    if parsed.directories:
        search_dir_path = parsed.directories[0]
        search_dir_title = initial_chips[0].get("label", search_dir_path)

    # Merge URL-driven filters (from facet sidebar clicks)
    url_dir = request.GET.get("in", "").strip()
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

    # Active filters for removable chips (URL-param-based only)
    active_filters = []
    if url_dir:
        active_filters.append(
            {"type": "in", "label": f"In: {url_dir}", "value": url_dir}
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
            "search_query_text": search_query_text,
            "search_dir_path": search_dir_path,
            "search_dir_title": search_dir_title,
            "initial_chips_json": initial_chips_json,
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
