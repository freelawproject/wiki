"""Periodic tasks for the pages app, run via cron management commands."""

from django.db.models import F, Sum


def sync_page_view_counts():
    """Sum PageViewTally records into Page.view_count and delete tallies.

    Returns the number of pages updated.
    """
    from .models import Page, PageViewTally

    tallies = PageViewTally.objects.values("page_id").annotate(
        total=Sum("count")
    )

    count = 0
    for entry in tallies:
        Page.objects.filter(id=entry["page_id"]).update(
            view_count=F("view_count") + entry["total"]
        )
        count += 1

    PageViewTally.objects.all().delete()
    return count


def update_search_vectors():
    """Update search_vector for all pages.

    Returns the number of pages updated.
    """
    from django.contrib.postgres.search import SearchVector

    from .models import Page

    count = Page.objects.update(
        search_vector=SearchVector("title", weight="A")
        + SearchVector("content", weight="B")
    )
    return count
