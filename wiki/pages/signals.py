"""CDN cache invalidation when pages change.

A ``post_save`` on ``Page`` invalidates the page's URL plus its parent
directory listing(s). When a slug or directory change makes the page's
URL move, the *old* URL is invalidated as well so its cached HTML
(which would otherwise become a redirect destination's stale duplicate)
gets evicted.

We don't hook ``post_delete`` because pages soft-delete via
``save(update_fields=[...])`` — that path goes through ``post_save``.
Hard delete is admin-only and accepted as not-invalidated.

Invalidations fire via ``transaction.on_commit`` so a rolled-back save
doesn't burn a CloudFront invalidation slot on a write that didn't
actually happen.
"""

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from wiki.lib.cloudfront import invalidate_paths

from .models import Page


def _parent_listing_paths(directory):
    """Return URLs of the listing(s) that contain pages in this directory.

    Django routes both ``/c/foo`` and ``/c/foo/`` to the directory view, so
    CloudFront caches them as separate keys — we have to invalidate both.
    """
    if directory and directory.path:
        return [f"/c/{directory.path}", f"/c/{directory.path}/"]
    return ["/"]


def _page_url_variants(content_path):
    """Return both slash-forms of a page URL.

    A page lives at ``/c/<path>``; some links/sitemaps emit it that way,
    others append a slash. Cache both.
    """
    return [f"/c/{content_path}", f"/c/{content_path}/"]


@receiver(pre_save, sender=Page)
def capture_old_path(sender, instance, **kwargs):
    """Stash pre-save URL state so post_save can invalidate the old URL.

    Uses ``all_objects`` so this also captures the prior path of pages
    that are about to be soft-deleted or restored.
    """
    if not instance.pk:
        instance._old_content_path = None
        instance._old_directory = None
        return
    old = (
        Page.all_objects.filter(pk=instance.pk)
        .only("slug", "directory_id")
        .select_related("directory")
        .first()
    )
    if old is None:
        instance._old_content_path = None
        instance._old_directory = None
        return
    instance._old_content_path = old.content_path
    instance._old_directory = old.directory


@receiver(post_save, sender=Page)
def invalidate_on_page_save(sender, instance, **kwargs):
    paths = set(_page_url_variants(instance.content_path))
    paths.update(_parent_listing_paths(instance.directory))
    old_path = getattr(instance, "_old_content_path", None)
    if old_path is None:
        # New page — no prior URL or parent listing to evict.
        transaction.on_commit(lambda: invalidate_paths(paths))
        return
    if old_path != instance.content_path:
        # Slug or directory moved — old URL must also drop out of the cache.
        paths.update(_page_url_variants(old_path))
    old_directory = getattr(instance, "_old_directory", None)
    if old_directory != instance.directory:
        # Directory changed — old parent's listing showed this page.
        paths.update(_parent_listing_paths(old_directory))
    transaction.on_commit(lambda: invalidate_paths(paths))
