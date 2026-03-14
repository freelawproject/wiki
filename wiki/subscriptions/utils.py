"""Subscription resolution helpers.

These determine who is subscribed to a page or directory, considering
direct subscriptions, directory subscriptions, and exclusions.
"""

from django.contrib.auth.models import User

from wiki.directories.models import Directory

from .models import (
    DirectorySubscription,
    PageSubscription,
    SubscriptionExclusion,
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


def get_subscriber_info_for_page(page):
    """Return subscriber info for a page.

    Returns:
        (page_sub_user_ids, dir_sub_mapping)
        page_sub_user_ids: set of user IDs with direct PageSubscription
        dir_sub_mapping: dict {user_id: Directory} for users subscribed
            via a directory. Maps to the most specific covering directory.
    """
    page_sub_users = set(
        PageSubscription.objects.filter(page=page).values_list(
            "user_id", flat=True
        )
    )

    ancestor_dirs = _get_ancestor_dir_list_for_page(page)
    if not ancestor_dirs:
        return page_sub_users, {}

    ancestor_dir_ids = [d.id for d in ancestor_dirs]

    # All directory subscriptions covering this page
    dir_subs = list(
        DirectorySubscription.objects.filter(
            directory_id__in=ancestor_dir_ids
        ).values_list("user_id", "directory_id")
    )
    if not dir_subs:
        return page_sub_users, {}

    user_ids = {uid for uid, _ in dir_subs}

    # Page-level exclusions
    page_excluded_users = set(
        SubscriptionExclusion.objects.filter(
            user_id__in=user_ids, page=page
        ).values_list("user_id", flat=True)
    )

    # Directory-level exclusions
    user_dir_exclusions = {}
    for uid, did in SubscriptionExclusion.objects.filter(
        user_id__in=user_ids, directory_id__in=ancestor_dir_ids
    ).values_list("user_id", "directory_id"):
        user_dir_exclusions.setdefault(uid, set()).add(did)

    # Build {directory_id: Directory} lookup
    dir_objects = {d.id: d for d in ancestor_dirs}

    # For each user, find the most specific unblocked subscription
    dir_sub_mapping = {}
    for uid, sub_dir_id in dir_subs:
        if uid in page_excluded_users:
            continue

        excluded_dirs = user_dir_exclusions.get(uid, set())

        # Check if path from page.directory to sub_dir is clear
        blocked = False
        if excluded_dirs:
            for d in ancestor_dirs:
                if d.id == sub_dir_id:
                    break  # Reached subscription point, path is clear
                if d.id in excluded_dirs:
                    blocked = True
                    break

        if blocked:
            continue

        # Use the most specific (closest to page) subscription
        sub_index = ancestor_dir_ids.index(sub_dir_id)
        if uid not in dir_sub_mapping:
            dir_sub_mapping[uid] = (sub_index, dir_objects[sub_dir_id])
        elif sub_index < dir_sub_mapping[uid][0]:
            dir_sub_mapping[uid] = (sub_index, dir_objects[sub_dir_id])

    # Strip the index, keep only Directory
    dir_sub_mapping = {uid: d for uid, (_, d) in dir_sub_mapping.items()}

    return page_sub_users, dir_sub_mapping


def is_effectively_subscribed_to_page(user, page):
    """Check if user is subscribed to this page (directly or via directory)."""
    if PageSubscription.objects.filter(user=user, page=page).exists():
        return True

    ancestor_dirs = _get_ancestor_dir_list_for_page(page)
    if not ancestor_dirs:
        return False

    ancestor_dir_ids = [d.id for d in ancestor_dirs]

    subs = list(
        DirectorySubscription.objects.filter(
            user=user, directory_id__in=ancestor_dir_ids
        ).values_list("directory_id", flat=True)
    )
    if not subs:
        return False

    if SubscriptionExclusion.objects.filter(user=user, page=page).exists():
        return False

    excluded_dirs = set(
        SubscriptionExclusion.objects.filter(
            user=user, directory_id__in=ancestor_dir_ids
        ).values_list("directory_id", flat=True)
    )

    # Check if any subscription has an unblocked path to the page
    for sub_dir_id in subs:
        blocked = False
        if excluded_dirs:
            for d in ancestor_dirs:
                if d.id == sub_dir_id:
                    break
                if d.id in excluded_dirs:
                    blocked = True
                    break
        if not blocked:
            return True

    return False


def is_effectively_subscribed_to_directory(user, directory):
    """Check if user is subscribed to this directory (directly or inherited)."""
    if DirectorySubscription.objects.filter(
        user=user, directory=directory
    ).exists():
        return True

    # Check parent subscriptions
    ancestor_dirs = _get_ancestor_dir_list(directory)
    ancestor_dir_ids = [d.id for d in ancestor_dirs]

    # Parent dir IDs (skip self since we already checked direct)
    parent_dir_ids = ancestor_dir_ids[1:]
    if not parent_dir_ids:
        return False

    subs = list(
        DirectorySubscription.objects.filter(
            user=user, directory_id__in=parent_dir_ids
        ).values_list("directory_id", flat=True)
    )
    if not subs:
        return False

    # Check exclusions along the path
    excluded_dirs = set(
        SubscriptionExclusion.objects.filter(
            user=user, directory_id__in=ancestor_dir_ids
        ).values_list("directory_id", flat=True)
    )

    for sub_dir_id in subs:
        blocked = False
        if excluded_dirs:
            for d in ancestor_dirs:
                if d.id == sub_dir_id:
                    break
                if d.id in excluded_dirs:
                    blocked = True
                    break
        if not blocked:
            return True

    return False


def get_effective_watchers_for_page(page):
    """Return queryset of Users watching this page (direct + directory)."""
    page_sub_users, dir_sub_mapping = get_subscriber_info_for_page(page)
    all_user_ids = page_sub_users | set(dir_sub_mapping.keys())
    if not all_user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=all_user_ids).select_related("profile")
