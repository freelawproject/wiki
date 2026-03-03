"""PostgreSQL full-text search for wiki pages.

Supports advanced query syntax (phrases, field filters, exclusions),
SQL-level permission filtering, highlighted snippets, and sorting.
"""

import functools
import operator

from django.contrib.postgres.search import (
    SearchHeadline,
    SearchQuery,
    SearchRank,
)
from django.db.models import F, Q, Value

from wiki.lib.permissions import viewable_pages_q

from .models import Page

SORT_OPTIONS = [
    ("relevance", "Relevance"),
    ("edited_desc", "Last edited (newest)"),
    ("edited_asc", "Last edited (oldest)"),
    ("created_desc", "Date created (newest)"),
    ("created_asc", "Date created (oldest)"),
    ("views", "Most viewed"),
    ("title", "Title A-Z"),
]


def _build_search_query(parsed):
    """Build a combined SearchQuery from parsed text and phrases.

    Returns None if there's no text or phrases (filter-only query).
    """
    queries = []
    if parsed.text:
        queries.append(SearchQuery(parsed.text, search_type="plain"))
    for phrase in parsed.phrases:
        queries.append(SearchQuery(phrase, search_type="phrase"))

    if not queries:
        return None

    return functools.reduce(operator.and_, queries)


def _apply_filters(qs, parsed):
    """Translate ParsedQuery fields into ORM filters."""
    for term in parsed.title_terms:
        qs = qs.filter(title__icontains=term)

    for term in parsed.content_terms:
        qs = qs.filter(content__icontains=term)

    if parsed.directories:
        dir_q = functools.reduce(
            operator.or_,
            [Q(directory__path__startswith=d) for d in parsed.directories],
        )
        qs = qs.filter(dir_q)

    if parsed.owners:
        owner_q = functools.reduce(
            operator.or_,
            [Q(owner__username__icontains=o) for o in parsed.owners],
        )
        qs = qs.filter(owner_q)

    if parsed.visibility:
        qs = qs.filter(visibility=parsed.visibility)

    if parsed.before_date:
        qs = qs.filter(updated_at__date__lte=parsed.before_date)

    if parsed.after_date:
        qs = qs.filter(updated_at__date__gte=parsed.after_date)

    for term in parsed.excluded:
        qs = qs.exclude(Q(title__icontains=term) | Q(content__icontains=term))

    return qs


def _apply_sort(qs, sort):
    """Apply sort ordering to the queryset."""
    if sort == "edited_desc":
        return qs.order_by("-updated_at")
    if sort == "edited_asc":
        return qs.order_by("updated_at")
    if sort == "created_desc":
        return qs.order_by("-created_at")
    if sort == "created_asc":
        return qs.order_by("created_at")
    if sort == "views":
        return qs.order_by("-view_count")
    if sort == "title":
        return qs.order_by("title")
    # Default: relevance
    return qs.order_by("-rank")


def search_pages(parsed, user=None, sort="relevance"):
    """Search pages with SQL-level permission filtering.

    Returns (queryset, total_count). The queryset is annotated with
    rank and headline (when a text query is present).
    """
    query = _build_search_query(parsed)

    qs = Page.objects.filter(viewable_pages_q(user)).select_related(
        "directory", "owner"
    )

    if query:
        qs = qs.filter(search_vector=query).annotate(
            rank=SearchRank(F("search_vector"), query),
            headline=SearchHeadline(
                "content",
                query,
                start_sel="<mark>",
                stop_sel="</mark>",
                max_words=60,
                min_words=20,
            ),
        )
    else:
        qs = qs.annotate(rank=Value(0), headline=Value(""))

    qs = _apply_filters(qs, parsed)
    qs = _apply_sort(qs, sort)
    qs = qs.distinct()

    total_count = qs.count()
    return qs, total_count
