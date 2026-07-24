"""Subscription resolution helpers.

These determine who is subscribed to a page or directory using the
same walk-up-the-ancestor-tree pattern as visibility / editability /
in_sitemap / in_llms_txt:

- An explicit record (SUBSCRIBED or UNSUBSCRIBED) overrides whatever
  the user would inherit from a parent directory.
- The absence of a record means "inherit from parent".
- The implicit default at the root is UNSUBSCRIBED.
"""

from django.contrib.auth.models import User

from wiki.directories.models import Directory

from .models import (
    DirectorySubscription,
    PageSubscription,
    SubscriptionStatus,
)


def _get_ancestor_dir_list(directory):
    """Return [directory, parent, grandparent, ..., root]."""
    dirs = []
    current = directory
    while current:
        dirs.append(current)
        current = current.parent
    return dirs


def _get_ancestor_dir_list_for_page(page):
    """Get ordered ancestor directories for a page.

    Returns [page.directory, parent, ..., root].
    Pages without a directory are treated as being in the root.
    """
    if page.directory_id:
        return _get_ancestor_dir_list(page.directory)
    root = Directory.objects.filter(path="").first()
    return [root] if root else []


def _resolve_dir_status_for_user(user_id, ancestor_dirs):
    """Walk ancestor dirs and return (status, directory) of the first override.

    Returns None if no DirectorySubscription exists in the chain
    (meaning the implicit default — UNSUBSCRIBED — applies).
    """
    if not ancestor_dirs:
        return None

    ancestor_dir_ids = [d.id for d in ancestor_dirs]
    dir_index = {d.id: i for i, d in enumerate(ancestor_dirs)}

    subs = DirectorySubscription.objects.filter(
        user_id=user_id, directory_id__in=ancestor_dir_ids
    ).values_list("directory_id", "status")

    # Find the closest (lowest index = most specific) override
    best = None
    for did, status in subs:
        idx = dir_index[did]
        if best is None or idx < best[0]:
            best = (idx, status, ancestor_dirs[idx])

    if best is None:
        return None
    return best[1], best[2]  # (status, directory)


def is_effectively_subscribed_to_page(user, page):
    """Check if user is subscribed to this page (directly or via directory).

    Resolution order (first explicit record wins):
    1. PageSubscription for this page
    2. Walk up directories: first DirectorySubscription found
    3. Default: not subscribed
    """
    page_sub = (
        PageSubscription.objects.filter(user=user, page=page)
        .values_list("status", flat=True)
        .first()
    )
    if page_sub is not None:
        return page_sub == SubscriptionStatus.SUBSCRIBED

    ancestor_dirs = _get_ancestor_dir_list_for_page(page)
    result = _resolve_dir_status_for_user(user.id, ancestor_dirs)
    if result is not None:
        return result[0] == SubscriptionStatus.SUBSCRIBED

    return False


def is_effectively_subscribed_to_directory(user, directory):
    """Check if user is subscribed to this directory (directly or inherited).

    Resolution order (first explicit record wins):
    1. DirectorySubscription for this directory
    2. Walk up parent directories
    3. Default: not subscribed
    """
    ancestor_dirs = _get_ancestor_dir_list(directory)
    result = _resolve_dir_status_for_user(user.id, ancestor_dirs)
    if result is not None:
        return result[0] == SubscriptionStatus.SUBSCRIBED

    return False


def get_subscriber_info_for_page(page):
    """Return subscriber info for a page.

    Returns:
        (page_sub_user_ids, dir_sub_mapping)
        page_sub_user_ids: set of user IDs with explicit SUBSCRIBED
            PageSubscription (these get page-style emails)
        dir_sub_mapping: dict {user_id: Directory} for users subscribed
            via a directory (these get directory-style emails with the
            covering directory identified)
    """
    # Step 1: page-level overrides
    page_records = dict(
        PageSubscription.objects.filter(page=page).values_list(
            "user_id", "status"
        )
    )
    page_sub_user_ids = {
        uid
        for uid, status in page_records.items()
        if status == SubscriptionStatus.SUBSCRIBED
    }

    # Step 2: directory-level resolution
    ancestor_dirs = _get_ancestor_dir_list_for_page(page)
    if not ancestor_dirs:
        return page_sub_user_ids, {}

    ancestor_dir_ids = [d.id for d in ancestor_dirs]
    dir_index = {d.id: i for i, d in enumerate(ancestor_dirs)}
    dir_objects = {d.id: d for d in ancestor_dirs}

    all_dir_subs = list(
        DirectorySubscription.objects.filter(
            directory_id__in=ancestor_dir_ids
        ).values_list("user_id", "directory_id", "status")
    )
    if not all_dir_subs:
        return page_sub_user_ids, {}

    # For each user, find the closest (most specific) dir override
    user_closest = {}  # user_id -> (index, dir_id, status)
    for uid, did, status in all_dir_subs:
        idx = dir_index[did]
        if uid not in user_closest or idx < user_closest[uid][0]:
            user_closest[uid] = (idx, did, status)

    # Build dir_sub_mapping for users whose closest record is SUBSCRIBED
    dir_sub_mapping = {}
    for uid, (_, did, status) in user_closest.items():
        # Page-level override takes precedence — skip users handled above
        if uid in page_records:
            continue
        if status == SubscriptionStatus.SUBSCRIBED:
            dir_sub_mapping[uid] = dir_objects[did]

    return page_sub_user_ids, dir_sub_mapping


def get_effective_watchers_for_page(page):
    """Return queryset of Users watching this page (direct + directory)."""
    page_sub_users, dir_sub_mapping = get_subscriber_info_for_page(page)
    all_user_ids = page_sub_users | set(dir_sub_mapping.keys())
    if not all_user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=all_user_ids).select_related("profile")
