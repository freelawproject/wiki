"""Shared permission checks for the wiki.

Permission hierarchy:
- System owner: full access to everything
- Page owner: full access to their page
- PagePermission / DirectoryPermission: granular per-user/group/domain grants
- Visibility baseline: PUBLIC pages viewable by anyone, INTERNAL by staff
  (the "internal" audience — see wiki.lib.access.is_internal_user), PRIVATE
  by explicit grant only.

Grants are *additive at any visibility level*: a view/edit/owner grant to a
user, group, or domain — on the item or any ancestor directory — adds that
audience on top of the baseline without changing the item's visibility. Grant
checks run ahead of the internal branch and pierce the directory gate, so a
guest with a grant on an internal page sees it while the page stays
internal. Directory permissions inherit down the parent chain.

Settings inheritance: visibility, editability, in_sitemap, and in_llms_txt
can be set to "inherit" to resolve from the nearest ancestor with an
explicit value. Use resolve_effective_value() for single-object checks and
resolve_all_directory_settings() for bulk queries.
"""

from django.db.models import Q
from django.utils import timezone

from wiki.directories.models import Directory, DirectoryPermission
from wiki.lib.access import is_internal_user
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


def _user_domain(user):
    """Return the lowercased domain of the user's email (cached, '' if none)."""
    if not hasattr(user, "_email_domain_cache"):
        email = (getattr(user, "email", "") or "").strip().lower()
        user._email_domain_cache = (
            email.rsplit("@", 1)[1] if "@" in email else ""
        )
    return user._email_domain_cache


def _grant_target_q(user):
    """Q matching permission rows granted to this user, their groups, or domain.

    Domain grants are stored as a normalized string (``grant_domain``), so a
    grant on the user's email domain matches regardless of whether that domain
    is currently on the sign-in allowlist (dormant grants still match; the
    allowlist is what gates login).
    """
    group_ids = _user_group_ids(user)
    q = Q(user=user)
    if group_ids:
        q = q | Q(group_id__in=group_ids)
    domain = _user_domain(user)
    if domain:
        q = q | Q(grant_domain=domain)
    return q


def can_view_directory(user, directory):
    """Check if user can view a directory.

    PUBLIC directories are viewable by anyone. A grant (any level) to the user,
    their group, or their domain — on this directory or any ancestor, or
    ownership of one — grants access regardless of visibility. INTERNAL
    directories are additionally viewable by staff (the internal audience).
    PRIVATE directories are visible only via such a grant or ownership.
    """
    # Root directory is always accessible
    if directory.path == "":
        return True

    effective_visibility, _ = resolve_effective_value(directory, "visibility")

    if effective_visibility == "public":
        return True

    if not user.is_authenticated:
        return False

    if is_system_owner(user):
        return True

    # Ownership of / explicit grant on this directory or any ancestor
    # (additive — applies whatever the visibility).
    d = directory
    while d is not None:
        if d.owner_id == user.id:
            return True
        if d.permissions.filter(_grant_target_q(user)).exists():
            return True
        d = d.parent

    # Baseline: internal directories are visible to the staff audience.
    if effective_visibility == "internal" and is_internal_user(user):
        return True

    return False


def can_view_page(user, page):
    """Check if user can view a page.

    PUBLIC pages are viewable by anyone (including anonymous). A grant (any
    level) to the user, their group, or their domain — on the page or any
    ancestor directory — grants access regardless of visibility and pierces
    the directory gate. INTERNAL pages are additionally viewable by staff (the
    internal audience) who can see the page's directory. PRIVATE pages are
    visible only via ownership or a grant.
    """
    effective_visibility, _ = resolve_effective_value(page, "visibility")

    if effective_visibility == "public":
        return True

    if not user.is_authenticated:
        return False

    if is_system_owner(user) or page.owner_id == user.id:
        return True

    # Explicit grant on the page (additive; pierces the directory gate).
    if page.permissions.filter(_grant_target_q(user)).exists():
        return True

    # Explicit grant on any ancestor directory.
    directory = page.directory
    while directory is not None:
        if directory.permissions.filter(_grant_target_q(user)).exists():
            return True
        directory = directory.parent

    # Baseline: internal pages are viewable by staff who can see the directory.
    if (
        effective_visibility == "internal"
        and is_internal_user(user)
        and (
            page.directory is None or can_view_directory(user, page.directory)
        )
    ):
        return True

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


def _expand_descendant_dirs(seed_dir_ids):
    """Return ``seed_dir_ids`` plus every directory nested beneath them.

    A grant (or ownership) on a directory cascades to its whole subtree, so we
    BFS the parent→children map once. Returns a set; empty in, empty out.
    """
    seed = set(seed_dir_ids)
    if not seed:
        return seed
    children_map = {}
    for did, pid in Directory.objects.values_list("id", "parent_id"):
        children_map.setdefault(pid, []).append(did)
    queue = list(seed)
    visited = set(seed)
    while queue:
        current = queue.pop(0)
        for child_id in children_map.get(current, []):
            if child_id not in visited:
                visited.add(child_id)
                queue.append(child_id)
    return visited


def _page_grant_q(user, prefix=""):
    """Q matching pages whose ``<prefix>permissions`` grant the user access.

    ``prefix`` lets the same shape target page-level (``""``) or
    directory-level (``"directory__"``) permission joins.
    """
    field = f"{prefix}permissions"
    q = Q(**{f"{field}__user": user})
    group_ids = _user_group_ids(user)
    if group_ids:
        q = q | Q(**{f"{field}__group_id__in": group_ids})
    domain = _user_domain(user)
    if domain:
        q = q | Q(**{f"{field}__grant_domain": domain})
    return q


def viewable_pages_q(user):
    """Return a Q filter for pages the user can view (used by search/listings).

    Two layers, matching can_view_page():
    - *Ambient* visibility (public, and internal for the staff audience) is
      gated by the directory — a page in a directory the user can't see is
      hidden from listings even if the page itself is public. (This is the
      long-standing search/listing behavior; direct URL access to a public
      page is governed separately by can_view_page.)
    - *Explicit* grants/ownership (user/group/domain, on the page or any
      ancestor directory) pierce that gate and match at any visibility.
    """
    if is_system_owner(user):
        return Q()

    public_dir_ids = _effectively_matching_dir_ids("visibility", {"public"})
    eff_public = Q(visibility="public") | Q(
        visibility="inherit", directory_id__in=public_dir_ids
    )

    dir_ids = _viewable_directory_ids(user)
    dir_gate = Q(directory__isnull=True) | Q(directory_id__in=dir_ids)

    if not user.is_authenticated:
        return eff_public & dir_gate

    # Explicit grants and ownership pierce the directory gate.
    q = Q(owner=user) | _page_grant_q(user)
    # A grant on a directory covers its whole subtree.
    granted_dir_ids = _expand_descendant_dirs(
        DirectoryPermission.objects.filter(_grant_target_q(user)).values_list(
            "directory_id", flat=True
        )
    )
    if granted_dir_ids:
        q |= Q(directory_id__in=granted_dir_ids)

    # Ambient visibility, gated by the directory: public for everyone, internal
    # for the staff audience.
    ambient = eff_public
    if is_internal_user(user):
        internal_dir_ids = _effectively_matching_dir_ids(
            "visibility", {"internal"}
        )
        ambient |= Q(visibility="internal") | Q(
            visibility="inherit", directory_id__in=internal_dir_ids
        )
    q |= ambient & dir_gate

    return q


def can_edit_page(user, page):
    """Check if user may change a page's title/content.

    Editing requires view access first. "Edit" is content-only; managing
    permissions, visibility/editability, and deletion require
    can_administer_page(). An EDIT or OWNER grant (user/group/domain) on the
    page or any ancestor directory grants edit regardless of visibility; the
    internal-editability baseline additionally grants it to the staff audience.
    """
    if not user.is_authenticated:
        return False

    if not can_view_page(user, page):
        return False

    if is_system_owner(user) or page.owner_id == user.id:
        return True

    # EDIT/OWNER grant on the page (additive, any visibility).
    edit_types = [
        PagePermission.PermissionType.EDIT,
        PagePermission.PermissionType.OWNER,
    ]
    if page.permissions.filter(
        _grant_target_q(user),
        permission_type__in=edit_types,
    ).exists():
        return True

    # Walk up directory ancestry for EDIT/OWNER.
    dir_edit_types = [
        DirectoryPermission.PermissionType.EDIT,
        DirectoryPermission.PermissionType.OWNER,
    ]
    directory = page.directory
    while directory is not None:
        if directory.permissions.filter(
            _grant_target_q(user),
            permission_type__in=dir_edit_types,
        ).exists():
            return True
        directory = directory.parent

    # Baseline: internal editability is editable by the staff audience.
    effective_editability, _ = resolve_effective_value(page, "editability")
    if effective_editability == "internal" and is_internal_user(user):
        return True

    return False


def can_edit_directory(user, directory):
    """Check if user may change a directory's content/metadata at the content
    level. Structural actions (permissions, settings, delete, move) require
    can_administer_directory().
    """
    if not user.is_authenticated:
        return False

    if not can_view_directory(user, directory):
        return False

    if is_system_owner(user) or directory.owner_id == user.id:
        return True

    edit_types = [
        DirectoryPermission.PermissionType.EDIT,
        DirectoryPermission.PermissionType.OWNER,
    ]
    # EDIT/OWNER grant on this directory or any ancestor (additive).
    d = directory
    while d is not None:
        if d.permissions.filter(
            _grant_target_q(user),
            permission_type__in=edit_types,
        ).exists():
            return True
        d = d.parent

    # Baseline: internal editability is editable by the staff audience.
    effective_editability, _ = resolve_effective_value(
        directory, "editability"
    )
    if effective_editability == "internal" and is_internal_user(user):
        return True

    return False


def can_administer_page(user, page):
    """Check if user may manage a page: permissions, visibility/editability,
    and deletion.

    Owner-level only: the system owner, the page's owner (its creator), or an
    OWNER-type grant (user/group/domain) on the page or any ancestor directory.
    Plain editors and the internal-editability baseline do *not* confer this —
    that's what keeps an "edit only" grant to an outside org safe.
    """
    if not user.is_authenticated:
        return False

    if is_system_owner(user) or page.owner_id == user.id:
        return True

    if page.permissions.filter(
        _grant_target_q(user),
        permission_type=PagePermission.PermissionType.OWNER,
    ).exists():
        return True

    directory = page.directory
    while directory is not None:
        if directory.permissions.filter(
            _grant_target_q(user),
            permission_type=DirectoryPermission.PermissionType.OWNER,
        ).exists():
            return True
        directory = directory.parent

    return False


def can_administer_directory(user, directory):
    """Check if user may manage a directory: permissions, settings, delete,
    move, and apply-to-children. Owner-level only (see can_administer_page).
    """
    if not user.is_authenticated:
        return False

    if is_system_owner(user):
        return True

    d = directory
    while d is not None:
        if d.owner_id == user.id:
            return True
        if d.permissions.filter(
            _grant_target_q(user),
            permission_type=DirectoryPermission.PermissionType.OWNER,
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

    # Internal editability is editable only by the staff audience.
    if is_internal_user(user):
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

    # Pages with an EDIT/OWNER grant (user/group/domain)
    edit_types = [
        PagePermission.PermissionType.EDIT,
        PagePermission.PermissionType.OWNER,
    ]
    ids.update(
        PagePermission.objects.filter(
            _grant_target_q(user),
            permission_type__in=edit_types,
        ).values_list("page_id", flat=True)
    )

    # Pages in directories the user owns or has an EDIT/OWNER grant on
    dir_edit_types = [
        DirectoryPermission.PermissionType.EDIT,
        DirectoryPermission.PermissionType.OWNER,
    ]

    # Directories user owns
    owned_dir_ids = set(
        Directory.objects.filter(owner=user).values_list("id", flat=True)
    )

    # Directories with an EDIT/OWNER grant (user/group/domain)
    perm_dir_ids = set(
        DirectoryPermission.objects.filter(
            _grant_target_q(user),
            permission_type__in=dir_edit_types,
        ).values_list("directory_id", flat=True)
    )

    # Include every page beneath an editable directory.
    editable_dir_ids = _expand_descendant_dirs(owned_dir_ids | perm_dir_ids)
    if editable_dir_ids:
        ids.update(
            Page.objects.filter(directory_id__in=editable_dir_ids).values_list(
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


def mark_domain_grants_dormant(domain):
    """Stamp ``dormant_since`` on a domain's grants when it leaves the allowlist.

    The grants are kept (so re-adding the domain restores access untouched) but
    flagged so the cleanup job can expire them after the retention window. Only
    rows not already dormant are stamped, so the clock isn't reset on repeats.
    """
    now = timezone.now()
    for model in (PagePermission, DirectoryPermission):
        model.objects.filter(
            grant_domain=domain, dormant_since__isnull=True
        ).update(dormant_since=now)


def reactivate_domain_grants(domain):
    """Clear ``dormant_since`` on a domain's grants when it returns to the
    allowlist, reactivating them and resetting the expiry clock."""
    for model in (PagePermission, DirectoryPermission):
        model.objects.filter(
            grant_domain=domain, dormant_since__isnull=False
        ).update(dormant_since=None)
