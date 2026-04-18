"""Shared permission checks for the wiki.

Permission hierarchy:
- System owner: full access to everything
- Page owner: full access to their page
- PagePermission / DirectoryPermission: granular per-user/group grants
- Visibility: PUBLIC pages viewable by anyone, INTERNAL by any
  authenticated user, PRIVATE by explicit permission only

Directory permissions are inherited: we walk up the parent chain.

Settings inheritance: visibility, editability, in_sitemap, and in_llms_txt
can be set to "inherit" to resolve from the nearest ancestor with an
explicit value. Use resolve_effective_value() for single-object checks and
resolve_all_directory_settings() for bulk queries.
"""

from django.db.models import Q

from wiki.directories.models import Directory, DirectoryPermission
from wiki.lib.inheritance import (
    resolve_all_directory_settings,
    resolve_effective_value,
)
from wiki.pages.models import Page, PagePermission
from wiki.users.models import SystemConfig


def is_system_owner(user):
    """Check if user is the system owner (first user / admin)."""
    if not user.is_authenticated:
        return False
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

    effective_visibility, _ = resolve_effective_value(directory, "visibility")

    if effective_visibility == "public":
        return True

    if not user.is_authenticated:
        return False

    if effective_visibility == "internal":
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
    effective_visibility, _ = resolve_effective_value(page, "visibility")

    if effective_visibility == "public":
        return True

    if not user.is_authenticated:
        return False

    # Directory gate: user must be able to view the page's directory
    if page.directory and not can_view_directory(user, page.directory):
        return False

    if effective_visibility == "internal":
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


def _viewable_directory_ids(user):
    """Return the set of directory IDs the user can view.

    Loads all directories (small table) and checks each via
    can_view_directory(). Called once per search request.
    """
    return {
        d.id for d in Directory.objects.all() if can_view_directory(user, d)
    }


def _effectively_matching_dir_ids(field_name, values):
    """Return directory IDs whose effective field value is in `values`.

    Uses bulk resolution to handle inheritance.
    """
    resolved = resolve_all_directory_settings(field_name)
    return {
        dir_id
        for dir_id, (eff_value, _, _) in resolved.items()
        if eff_value in values
    }


def viewable_pages_q(user):
    """Return a Q filter for pages the user can view.

    Translates the can_view_page() logic into SQL-level filtering
    so that LIMIT/OFFSET apply to already-filtered results.
    Handles both explicit and inherited visibility values.
    """
    if is_system_owner(user):
        return Q()

    dir_ids = _viewable_directory_ids(user)
    dir_gate = Q(directory__isnull=True) | Q(directory_id__in=dir_ids)

    # Directory IDs where effective visibility is public
    public_dir_ids = _effectively_matching_dir_ids("visibility", {"public"})
    # Directory IDs where effective visibility is public or internal
    pub_int_dir_ids = _effectively_matching_dir_ids(
        "visibility", {"public", "internal"}
    )
    # Directory IDs where effective visibility is private
    private_dir_ids = _effectively_matching_dir_ids("visibility", {"private"})

    if not user.is_authenticated:
        # Anonymous: only see explicitly public pages + inheriting-public
        return (
            Q(visibility="public")
            | Q(visibility="inherit", directory_id__in=public_dir_ids)
        ) & dir_gate

    # Authenticated user
    group_ids = _user_group_ids(user)

    # Public or internal pages (explicit or inherited) in viewable dirs
    public_internal = (
        Q(visibility__in=["public", "internal"])
        | Q(visibility="inherit", directory_id__in=pub_int_dir_ids)
    ) & dir_gate

    # Private pages (explicit or inherited) the user owns
    private_q = Q(visibility="private") | Q(
        visibility="inherit", directory_id__in=private_dir_ids
    )
    private_owned = private_q & Q(owner=user) & dir_gate

    # Private pages with explicit page-level permission (user or groups)
    perm_q = Q(permissions__user=user)
    if group_ids:
        perm_q = perm_q | Q(permissions__group_id__in=group_ids)
    private_permitted = private_q & perm_q & dir_gate

    # Private pages with directory-level permission (inherited)
    dir_perm_q = Q(directory__permissions__user=user)
    if group_ids:
        dir_perm_q = dir_perm_q | Q(
            directory__permissions__group_id__in=group_ids
        )
    private_dir_permitted = private_q & dir_perm_q & dir_gate

    return (
        public_internal
        | private_owned
        | private_permitted
        | private_dir_permitted
    )


def can_edit_page(user, page):
    """Check if user can edit a page.

    Editing requires view access first — a user who cannot see a page
    must not be able to edit it, regardless of editability settings.
    """
    if not user.is_authenticated:
        return False

    if not can_view_page(user, page):
        return False

    effective_editability, _ = resolve_effective_value(page, "editability")

    if effective_editability == "internal":
        return True

    if is_system_owner(user):
        return True

    if page.owner_id == user.id:
        return True

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
    """Check if user can edit a directory.

    Editing requires view access first — a user who cannot see a
    directory must not be able to edit it, regardless of editability.
    """
    if not user.is_authenticated:
        return False

    if not can_view_directory(user, directory):
        return False

    effective_editability, _ = resolve_effective_value(
        directory, "editability"
    )

    if effective_editability == "internal":
        return True

    if is_system_owner(user):
        return True

    if directory.owner_id == user.id:
        return True

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


def editable_page_ids(user):
    """Return the set of page IDs the user can edit.

    Used by the review queue to find all pages with pending feedback.
    """
    if not user.is_authenticated:
        return set()

    if is_system_owner(user):
        return set(Page.objects.values_list("id", flat=True))

    ids = set()

    # Pages the user owns
    ids.update(Page.objects.filter(owner=user).values_list("id", flat=True))

    # Pages with editability="internal" (explicit)
    ids.update(
        Page.objects.filter(editability="internal").values_list(
            "id", flat=True
        )
    )

    # Pages inheriting editability="internal" from their directory
    internal_edit_dir_ids = _effectively_matching_dir_ids(
        "editability", {"internal"}
    )
    if internal_edit_dir_ids:
        ids.update(
            Page.objects.filter(
                editability="inherit",
                directory_id__in=internal_edit_dir_ids,
            ).values_list("id", flat=True)
        )

    # Pages with explicit EDIT/OWNER PagePermission
    edit_types = [
        PagePermission.PermissionType.EDIT,
        PagePermission.PermissionType.OWNER,
    ]
    ids.update(
        PagePermission.objects.filter(
            _user_or_group_q(user),
            permission_type__in=edit_types,
        ).values_list("page_id", flat=True)
    )

    # Pages in directories the user owns or has EDIT/OWNER permission on
    dir_edit_types = [
        DirectoryPermission.PermissionType.EDIT,
        DirectoryPermission.PermissionType.OWNER,
    ]

    # Directories user owns
    owned_dir_ids = set(
        Directory.objects.filter(owner=user).values_list("id", flat=True)
    )

    # Directories with explicit permission
    perm_dir_ids = set(
        DirectoryPermission.objects.filter(
            _user_or_group_q(user),
            permission_type__in=dir_edit_types,
        ).values_list("directory_id", flat=True)
    )

    editable_dir_ids = owned_dir_ids | perm_dir_ids

    # Walk children via BFS to include all descendant directories
    if editable_dir_ids:
        all_dirs = list(Directory.objects.values_list("id", "parent_id"))
        children_map = {}
        for did, pid in all_dirs:
            children_map.setdefault(pid, []).append(did)

        queue = list(editable_dir_ids)
        visited = set(editable_dir_ids)
        while queue:
            current = queue.pop(0)
            for child_id in children_map.get(current, []):
                if child_id not in visited:
                    visited.add(child_id)
                    queue.append(child_id)

        ids.update(
            Page.objects.filter(directory_id__in=visited).values_list(
                "id", flat=True
            )
        )

    # Enforce view access: a user cannot edit pages they cannot see
    # (e.g. pages in private directories with internal editability).
    viewable_q = viewable_pages_q(user)
    return ids & set(
        Page.objects.filter(viewable_q, id__in=ids).values_list(
            "id", flat=True
        )
    )
