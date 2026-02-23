"""Advisory edit-lock helpers for pages and directories."""

from django.utils import timezone

from wiki.lib.models import EditLock


def get_active_lock_for_page(page, exclude_user=None):
    """Return the active (non-expired) lock on *page* by another user, or None."""
    qs = EditLock.objects.filter(page=page, expires_at__gt=timezone.now())
    if exclude_user is not None:
        qs = qs.exclude(user=exclude_user)
    return qs.select_related("user", "user__profile").first()


def get_active_lock_for_directory(directory, exclude_user=None):
    """Return the active (non-expired) lock on *directory* by another user, or None."""
    qs = EditLock.objects.filter(
        directory=directory, expires_at__gt=timezone.now()
    )
    if exclude_user is not None:
        qs = qs.exclude(user=exclude_user)
    return qs.select_related("user", "user__profile").first()


def acquire_lock_for_page(page, user):
    """Acquire an edit lock on *page* for *user*.

    Deletes any existing locks on this page first.
    """
    EditLock.objects.filter(page=page).delete()
    return EditLock.objects.create(page=page, user=user)


def acquire_lock_for_directory(directory, user):
    """Acquire an edit lock on *directory* for *user*.

    Deletes any existing locks on this directory first.
    """
    EditLock.objects.filter(directory=directory).delete()
    return EditLock.objects.create(directory=directory, user=user)


def release_lock_for_page(page):
    """Release all edit locks on *page*."""
    EditLock.objects.filter(page=page).delete()


def release_lock_for_directory(directory):
    """Release all edit locks on *directory*."""
    EditLock.objects.filter(directory=directory).delete()


def cleanup_expired_locks():
    """Delete all expired edit locks. Returns the number deleted."""
    count, _ = EditLock.objects.filter(expires_at__lte=timezone.now()).delete()
    return count
