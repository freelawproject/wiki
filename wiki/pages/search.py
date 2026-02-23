"""PostgreSQL full-text search for wiki pages."""

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F

from wiki.lib.permissions import can_view_page

from .models import Page


def search_pages(query_str, user=None, limit=25):
    """Search pages using PostgreSQL full-text search.

    Results are permission-filtered: only pages the user can view
    are returned.
    """
    query = SearchQuery(query_str)
    pages = (
        Page.objects.filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .order_by("-rank")[:limit]
    )

    # Filter by permissions
    return [p for p in pages if can_view_page(user, p)]
