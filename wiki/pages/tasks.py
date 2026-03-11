"""Periodic tasks for the pages app, run via cron management commands."""

from datetime import timedelta

from django.contrib.postgres.search import SearchVector
from django.db.models import F, Sum
from django.utils import timezone

from .models import Page, PageViewTally


def sync_page_view_counts():
    """Sum PageViewTally records into Page.view_count and delete tallies.

    Returns the number of pages updated.
    """
    tallies = PageViewTally.objects.values("page_id").annotate(
        total=Sum("count")
    )

    count = 0
    for entry in tallies:
        Page.all_objects.filter(id=entry["page_id"]).update(
            view_count=F("view_count") + entry["total"]
        )
        count += 1

    PageViewTally.objects.all().delete()
    return count


def update_search_vectors():
    """Update search_vector for all pages.

    Returns the number of pages updated.
    """
    count = Page.objects.update(
        search_vector=SearchVector("title", weight="A")
        + SearchVector("content", weight="B")
    )
    return count


def purge_deleted_pages(days=90):
    """Permanently delete pages that were soft-deleted more than `days` ago.

    Returns the number of pages purged.
    """
    cutoff = timezone.now() - timedelta(days=days)
    qs = Page.all_objects.filter(is_deleted=True, deleted_at__lte=cutoff)
    count, _ = qs.delete()
    return count
