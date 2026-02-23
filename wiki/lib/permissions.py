"""Shared permission checks for the wiki.

Permission hierarchy:
- System owner: full access to everything
- Page owner: full access to their page
- PagePermission / DirectoryPermission: granular per-user/group grants
- Visibility: PUBLIC pages viewable by anyone, INTERNAL by any
  authenticated user, PRIVATE by explicit permission only

Directory permissions are inherited: we walk up the parent chain.
"""

from django.db.models import Q

# Openness ranking: higher number = more open
_VISIBILITY_OPENNESS = {
    "private": 0,
    "internal": 1,
    "public": 2,
}


def is_more_open_than(page_visibility, directory_visibility):
    """Return True if a page's visibility is more open than its directory's."""
    return _VISIBILITY_OPENNESS.get(
        page_visibility, 0
    ) > _VISIBILITY_OPENNESS.get(directory_visibility, 0)


def is_editability_more_open_than_visibility(editability, visibility):
    """FLP Staff editability + Private visibility is invalid."""
    return editability == "internal" and visibility == "private"


def is_system_owner(user):
    """Check if user is the system owner (first user / admin)."""
    if not user.is_authenticated:
        return False
    from wiki.users.models import SystemConfig

    try:
        config = SystemConfig.objects.get(pk=1)
        return config.owner_id == user.id
    except SystemConfig.DoesNotExist:
        return False


def _user_group_ids(user):
    """Return the user's group IDs (cached on the user object)."""
    if not hasattr(user, "_group_ids_cache"):
        user._group_ids_cache = set(user.groups.values_list("id", flat=True))
    return user._group_ids_cache


def _user_or_group_q(user):
    """Build a Q filter matching either the user or any of their groups."""
    group_ids = _user_group_ids(user)
    q = Q(user=user)
    if group_ids:
        q = q | Q(group_id__in=group_ids)
    return q


def can_view_directory(user, directory):
    """Check if user can view a directory.

    PUBLIC directories are viewable by anyone.
    INTERNAL directories are viewable by any authenticated user.
    PRIVATE directories require owner, system owner, or explicit permission.
    Permission is checked on this directory AND walks up ancestors —
    access to a parent grants access to children.
    """
    # Root directory is always accessible
    if directory.path == "":
        return True

    from wiki.directories.models import Directory

    if directory.visibility == Directory.Visibility.PUBLIC:
        return True

    if not user.is_authenticated:
        return False

    if directory.visibility == Directory.Visibility.INTERNAL:
        return True

    if is_system_owner(user):
        return True

    if directory.owner_id == user.id:
        return True

    # Check permissions on this directory (user or group, any type)
    if directory.permissions.filter(_user_or_group_q(user)).exists():
        return True

    # Walk up ancestors — if user has access to a parent, they can see children
    parent = directory.parent
    while parent is not None:
        if parent.permissions.filter(_user_or_group_q(user)).exists():
            return True
        if parent.owner_id == user.id:
            return True
        parent = parent.parent

    return False


def can_view_page(user, page):
    """Check if user can view a page.

    PUBLIC pages are viewable by anyone (including anonymous).
    INTERNAL pages are viewable by any authenticated user.
    PRIVATE pages require owner, system owner, or explicit permission.
    """
    from wiki.pages.models import Page

    if page.visibility == Page.Visibility.PUBLIC:
        return True

    if not user.is_authenticated:
        return False

    # Directory gate: user must be able to view the page's directory
    if page.directory and not can_view_directory(user, page.directory):
        return False

    if page.visibility == Page.Visibility.INTERNAL:
        return True

    if is_system_owner(user):
        return True

    if page.owner_id == user.id:
        return True

    # Check page-level permissions (user or group)
    if page.permissions.filter(_user_or_group_q(user)).exists():
        return True

    # Walk up directory ancestry
    directory = page.directory
    while directory is not None:
        if directory.permissions.filter(_user_or_group_q(user)).exists():
            return True
        directory = directory.parent

    return False


def can_edit_page(user, page):
    """Check if user can edit a page."""
    if not user.is_authenticated:
        return False

    if page.editability == "internal":
        return True

    if is_system_owner(user):
        return True

    if page.owner_id == user.id:
        return True

    from wiki.pages.models import PagePermission

    # Check page-level EDIT or OWNER permission
    edit_types = [
        PagePermission.PermissionType.EDIT,
        PagePermission.PermissionType.OWNER,
    ]
    if page.permissions.filter(
        _user_or_group_q(user),
        permission_type__in=edit_types,
    ).exists():
        return True

    # Walk up directory ancestry for EDIT/OWNER
    from wiki.directories.models import DirectoryPermission

    dir_edit_types = [
        DirectoryPermission.PermissionType.EDIT,
        DirectoryPermission.PermissionType.OWNER,
    ]
    directory = page.directory
    while directory is not None:
        if directory.permissions.filter(
            _user_or_group_q(user),
            permission_type__in=dir_edit_types,
        ).exists():
            return True
        directory = directory.parent

    return False


def can_edit_directory(user, directory):
    """Check if user can edit a directory."""
    if not user.is_authenticated:
        return False

    if directory.editability == "internal":
        return True

    if is_system_owner(user):
        return True

    if directory.owner_id == user.id:
        return True

    from wiki.directories.models import DirectoryPermission

    edit_types = [
        DirectoryPermission.PermissionType.EDIT,
        DirectoryPermission.PermissionType.OWNER,
    ]
    # Check this directory and walk up
    d = directory
    while d is not None:
        if d.permissions.filter(
            _user_or_group_q(user),
            permission_type__in=edit_types,
        ).exists():
            return True
        d = d.parent

    return False
