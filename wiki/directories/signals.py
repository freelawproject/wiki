"""CDN cache invalidation when directories change.

Saving a directory invalidates its own listing URL and the descendant
wildcard ``/c/<path>/*`` unconditionally. The wildcard always fires
because directory-level fields (e.g. ``visibility``) cascade to
descendant pages with ``visibility='inherit'`` — those page rows aren't
re-saved when the directory changes, so ``Page.post_save`` won't drop
their cached HTML. A rename additionally invalidates ``/c/<old>/*`` so
descendants at the previous path drop too.

Invalidations fire via ``transaction.on_commit`` so rolled-back saves
don't burn CloudFront invalidation paths.
"""

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from wiki.lib.cloudfront import invalidate_paths

from .models import Directory


def _listing_paths(path):
    """Return the URL(s) of a directory listing.

    Django routes both ``/c/foo`` and ``/c/foo/`` to the directory view,
    and both forms are cacheable. Invalidate both.
    """
    if path:
        return [f"/c/{path}", f"/c/{path}/"]
    return ["/"]


def _wildcard_paths(path):
    """Return wildcard(s) covering every descendant URL under a directory.

    ``/c/foo/*`` matches ``/c/foo/x`` and ``/c/foo/`` but NOT ``/c/foo``
    itself, so we emit the directory's own URL alongside the wildcard.
    """
    if path:
        return [f"/c/{path}", f"/c/{path}/*"]
    return ["/*"]


@receiver(pre_save, sender=Directory)
def capture_old_state(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_path = None
        instance._old_parent_id = None
        return
    old = (
        Directory.objects.filter(pk=instance.pk)
        .values("path", "parent_id")
        .first()
    )
    if old is None:
        instance._old_path = None
        instance._old_parent_id = None
        return
    instance._old_path = old["path"]
    instance._old_parent_id = old["parent_id"]


@receiver(post_save, sender=Directory)
def invalidate_on_directory_save(sender, instance, **kwargs):
    paths = set(_listing_paths(instance.path))

    # Descendant wildcard always fires — directory-level fields like
    # `visibility` cascade to inheriting pages whose rows aren't re-saved.
    paths.update(_wildcard_paths(instance.path))

    # Parent listing also needs to drop — child counts may have changed.
    parent_path = _parent_path_lookup(instance.parent_id)
    paths.update(_listing_paths(parent_path))

    old_path = getattr(instance, "_old_path", None)
    if old_path is not None and old_path != instance.path:
        # Rename — descendants at the OLD path also need to drop.
        paths.update(_wildcard_paths(old_path))

    old_parent_id = getattr(instance, "_old_parent_id", None)
    if old_parent_id is not None and old_parent_id != instance.parent_id:
        # Move — old parent listed this directory as a child.
        old_parent_path = _parent_path_lookup(old_parent_id)
        paths.update(_listing_paths(old_parent_path))

    transaction.on_commit(lambda: invalidate_paths(paths))


def _parent_path_lookup(parent_id):
    """Return the path of the directory with the given id, or "" for root/None."""
    if parent_id is None:
        return ""
    return (
        Directory.objects.filter(pk=parent_id)
        .values_list("path", flat=True)
        .first()
        or ""
    )
