"""Advisory edit-lock helpers for pages and directories."""

from django.utils import timezone

from wiki.lib.models import EditLock


def _get_active_lock(exclude_user=None, **filter_kw):
    """Return the active (non-expired) lock matching filter_kw, or None."""
    qs = EditLock.objects.filter(**filter_kw, expires_at__gt=timezone.now())
    if exclude_user is not None:
        qs = qs.exclude(user=exclude_user)
    return qs.select_related("user", "user__profile").first()


def _acquire_lock(user, **filter_kw):
    """Acquire an edit lock, deleting any existing locks first."""
    EditLock.objects.filter(**filter_kw).delete()
    return EditLock.objects.create(**filter_kw, user=user)


def _release_lock(**filter_kw):
    """Release all edit locks matching filter_kw."""
    EditLock.objects.filter(**filter_kw).delete()


def get_active_lock_for_page(page, exclude_user=None):
    """Return the active (non-expired) lock on *page* by another user, or None."""
    return _get_active_lock(page=page, exclude_user=exclude_user)


def get_active_lock_for_directory(directory, exclude_user=None):
    """Return the active (non-expired) lock on *directory* by another user, or None."""
    return _get_active_lock(directory=directory, exclude_user=exclude_user)


def acquire_lock_for_page(page, user):
    """Acquire an edit lock on *page* for *user*.

    Deletes any existing locks on this page first.
    """
    return _acquire_lock(page=page, user=user)


def acquire_lock_for_directory(directory, user):
    """Acquire an edit lock on *directory* for *user*.

    Deletes any existing locks on this directory first.
    """
    return _acquire_lock(directory=directory, user=user)


def release_lock_for_page(page):
    """Release all edit locks on *page*."""
    _release_lock(page=page)


def release_lock_for_directory(directory):
    """Release all edit locks on *directory*."""
    _release_lock(directory=directory)


def cleanup_expired_locks():
    """Delete all expired edit locks. Returns the number deleted."""
    count, _ = EditLock.objects.filter(expires_at__lte=timezone.now()).delete()
    return count
