"""Tests for shared lib: permissions, markdown, storage, edit locks."""

import pytest
import time_machine
from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from wiki.directories.models import Directory, DirectoryPermission
from wiki.lib.edit_lock import (
    acquire_lock_for_directory,
    acquire_lock_for_page,
    cleanup_expired_locks,
    get_active_lock_for_directory,
    get_active_lock_for_page,
    release_lock_for_directory,
    release_lock_for_page,
)
from wiki.lib.models import EditLock
from wiki.lib.permissions import (
    _bulk_administer_directory_resolver,
    _bulk_viewable_directory_resolver,
    _viewable_directory_ids,
    can_administer_directory,
    can_edit_directory,
    can_edit_page,
    can_view_directory,
    can_view_page,
    editable_page_ids,
    filter_administerable_directories,
    filter_viewable_directories,
    is_system_owner,
)
from wiki.pages.models import Page, PagePermission, PageRevision
from wiki.proposals.models import ChangeProposal
from wiki.users.models import SystemConfig


class TestIsSystemOwner:
    def test_owner_is_system_owner(self, owner_user):
        assert is_system_owner(owner_user)

    def test_regular_user_is_not(self, user):
        assert not is_system_owner(user)

    def test_anonymous_is_not(self, db):
        assert not is_system_owner(AnonymousUser())


class TestCanViewPage:
    def test_public_page_visible_to_anon(self, page):
        assert can_view_page(AnonymousUser(), page)

    def test_private_page_hidden_from_anon(self, private_page):
        assert not can_view_page(AnonymousUser(), private_page)

    def test_private_page_visible_to_owner(self, user, private_page):
        assert can_view_page(user, private_page)

    def test_private_page_visible_to_system_owner(
        self, owner_user, other_user, private_page
    ):
        # owner_user is system owner but not the page owner
        # private_page is owned by 'user' fixture
        # We need a different user as system owner
        SystemConfig.objects.all().delete()
        SystemConfig.objects.create(owner=other_user)
        assert can_view_page(other_user, private_page)

    def test_private_page_with_permission(self, other_user, user):
        p = Page.objects.create(
            title="Private Perm",
            slug="private-perm",
            visibility=Page.Visibility.PRIVATE,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        # other_user has no permission yet
        assert not can_view_page(other_user, p)
        # Grant view
        PagePermission.objects.create(
            page=p,
            user=other_user,
            permission_type=PagePermission.PermissionType.VIEW,
        )
        assert can_view_page(other_user, p)

    def test_private_page_with_directory_permission(
        self, other_user, user, sub_directory
    ):
        p = Page.objects.create(
            title="Dir Private",
            slug="dir-private",
            visibility=Page.Visibility.PRIVATE,
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        assert not can_view_page(other_user, p)
        DirectoryPermission.objects.create(
            directory=sub_directory,
            user=other_user,
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        assert can_view_page(other_user, p)

    def test_private_page_with_group_permission(self, other_user, user, group):
        p = Page.objects.create(
            title="Group Private",
            slug="group-private",
            visibility=Page.Visibility.PRIVATE,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        # other_user not in group yet
        assert not can_view_page(other_user, p)
        # Grant group VIEW
        PagePermission.objects.create(
            page=p,
            group=group,
            permission_type=PagePermission.PermissionType.VIEW,
        )
        # Still not visible — user not in group
        assert not can_view_page(other_user, p)
        # Add user to group
        other_user.groups.add(group)
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache
        assert can_view_page(other_user, p)

    def test_private_page_with_directory_group_permission(
        self, other_user, user, sub_directory, group
    ):
        p = Page.objects.create(
            title="Dir Group Private",
            slug="dir-group-private",
            visibility=Page.Visibility.PRIVATE,
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        assert not can_view_page(other_user, p)
        DirectoryPermission.objects.create(
            directory=sub_directory,
            group=group,
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        other_user.groups.add(group)
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache
        assert can_view_page(other_user, p)


class TestBulkViewableDirectoryResolver:
    """The bulk resolver (used by search, listings, and the move-target
    dropdown — see issue #145) must agree with can_view_directory() for
    every directory. A divergence here is a visibility bug, not just a
    performance regression, so this is checked directly against the
    per-item function across every visibility/inheritance/grant shape."""

    @pytest.fixture
    def carol(self, db):
        """A directory owner who is never one of the viewers under test,
        so ownership doesn't leak into the guest/staff/grant scenarios."""
        return User.objects.create_user(
            username="carol@free.law", email="carol@free.law"
        )

    @pytest.fixture
    def tree(self, root_directory, carol, other_user, group):
        top_public = Directory.objects.create(
            path="top-public",
            title="Top Public",
            parent=root_directory,
            owner=carol,
            visibility="public",
        )
        mid_private = Directory.objects.create(
            path="top-public/mid-private",
            title="Mid Private",
            parent=top_public,
            owner=carol,
            visibility="private",
        )
        leaf_public = Directory.objects.create(
            path="top-public/mid-private/leaf-public",
            title="Leaf Public",
            parent=mid_private,
            owner=carol,
            visibility="public",
        )
        leaf_inherit = Directory.objects.create(
            path="top-public/mid-private/leaf-inherit",
            title="Leaf Inherit",
            parent=mid_private,
            owner=carol,
            visibility="inherit",
        )
        top_internal = Directory.objects.create(
            path="top-internal",
            title="Top Internal",
            parent=root_directory,
            owner=carol,
            visibility="internal",
        )
        mid_inherit_internal = Directory.objects.create(
            path="top-internal/mid-inherit",
            title="Mid Inherit",
            parent=top_internal,
            owner=carol,
            visibility="inherit",
        )
        top_private_grant = Directory.objects.create(
            path="top-private-grant",
            title="Top Private Grant",
            parent=root_directory,
            owner=carol,
            visibility="private",
        )
        DirectoryPermission.objects.create(
            directory=top_private_grant,
            user=other_user,
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        mid_inherit_from_grant = Directory.objects.create(
            path="top-private-grant/mid-inherit",
            title="Mid Inherit Grant",
            parent=top_private_grant,
            owner=carol,
            visibility="inherit",
        )
        top_private_group = Directory.objects.create(
            path="top-private-group",
            title="Top Private Group",
            parent=root_directory,
            owner=carol,
            visibility="private",
        )
        DirectoryPermission.objects.create(
            directory=top_private_group,
            group=group,
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        top_private_domain = Directory.objects.create(
            path="top-private-domain",
            title="Top Private Domain",
            parent=root_directory,
            owner=carol,
            visibility="private",
        )
        DirectoryPermission.objects.create(
            directory=top_private_domain,
            grant_domain="free.law",
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        top_private_owner = Directory.objects.create(
            path="top-private-owner",
            title="Top Private Owner",
            parent=root_directory,
            owner=other_user,
            visibility="private",
        )
        return [
            root_directory,
            top_public,
            mid_private,
            leaf_public,
            leaf_inherit,
            top_internal,
            mid_inherit_internal,
            top_private_grant,
            mid_inherit_from_grant,
            top_private_group,
            top_private_domain,
            top_private_owner,
        ]

    def test_matches_for_anon_guest_group_and_staff(
        self, tree, user, other_user, group
    ):
        other_user.groups.add(group)
        staff_user = User.objects.create_user(
            username="dave@free.law", email="dave@free.law", is_staff=True
        )

        for viewer in (AnonymousUser(), user, other_user, staff_user):
            resolve = _bulk_viewable_directory_resolver(viewer)
            for d in tree:
                assert resolve(d.id) == can_view_directory(viewer, d), (
                    f"resolver disagreed with can_view_directory for "
                    f"{viewer} on {d.path!r}"
                )

    def test_matches_for_system_owner(self, tree, owner_user):
        resolve = _bulk_viewable_directory_resolver(owner_user)
        for d in tree:
            assert resolve(d.id) is True
            assert can_view_directory(owner_user, d) is True


class TestViewableDirectoryQueryCost:
    """Regression guard for issue #145: bulk visibility resolution must stay
    a fixed number of queries as the tree grows, not scale with directory
    count or nesting depth."""

    @staticmethod
    def _grow_tree(root, prefix, depth, siblings, owner):
        parent = root
        for i in range(depth):
            slug = f"{prefix}-{i}"
            path = f"{parent.path}/{slug}" if parent.path else slug
            parent = Directory.objects.create(
                path=path, title=slug, parent=parent, owner=owner
            )
        for i in range(siblings):
            Directory.objects.create(
                path=f"{prefix}-sib-{i}",
                title=f"{prefix} sib {i}",
                parent=root,
                owner=owner,
            )

    def test_viewable_directory_ids_query_count_is_flat(
        self, root_directory, user
    ):
        self._grow_tree(
            root_directory, "small", depth=2, siblings=2, owner=user
        )
        # Fetch a fresh user instance for each measurement — _user_group_ids,
        # _user_domain, and is_internal_user all cache on the user object, so
        # reusing one instance would make the second call look artificially
        # cheap regardless of tree size.
        with CaptureQueriesContext(connection) as small:
            _viewable_directory_ids(User.objects.get(pk=user.pk))

        self._grow_tree(
            root_directory, "big", depth=12, siblings=30, owner=user
        )
        with CaptureQueriesContext(connection) as big:
            _viewable_directory_ids(User.objects.get(pk=user.pk))

        assert len(big.captured_queries) == len(small.captured_queries)

    def test_filter_viewable_directories_query_count_is_flat(
        self, root_directory, user
    ):
        self._grow_tree(
            root_directory, "small", depth=2, siblings=2, owner=user
        )
        small_dirs = list(Directory.objects.all())
        with CaptureQueriesContext(connection) as small:
            filter_viewable_directories(
                User.objects.get(pk=user.pk), small_dirs
            )

        self._grow_tree(
            root_directory, "big", depth=12, siblings=30, owner=user
        )
        big_dirs = list(Directory.objects.all())
        with CaptureQueriesContext(connection) as big:
            filter_viewable_directories(User.objects.get(pk=user.pk), big_dirs)

        assert len(big.captured_queries) == len(small.captured_queries)


class TestBulkAdministerDirectoryResolver:
    """Same bulk-vs-live-walk equivalence check as
    TestBulkViewableDirectoryResolver, for the owner-level resolver used by
    the page-move destination dropdown (issue #149)."""

    @pytest.fixture
    def carol(self, db):
        return User.objects.create_user(
            username="carol@free.law", email="carol@free.law"
        )

    @pytest.fixture
    def tree(self, root_directory, carol, other_user, group):
        top_owned_by_other = Directory.objects.create(
            path="top-owned",
            title="Top Owned",
            parent=root_directory,
            owner=other_user,
        )
        mid_no_grant = Directory.objects.create(
            path="top-owned/mid",
            title="Mid",
            parent=top_owned_by_other,
            owner=carol,
        )
        top_grant = Directory.objects.create(
            path="top-grant",
            title="Top Grant",
            parent=root_directory,
            owner=carol,
        )
        DirectoryPermission.objects.create(
            directory=top_grant,
            user=other_user,
            permission_type=DirectoryPermission.PermissionType.OWNER,
        )
        mid_inherits_grant = Directory.objects.create(
            path="top-grant/mid",
            title="Mid Grant",
            parent=top_grant,
            owner=carol,
        )
        top_group_grant = Directory.objects.create(
            path="top-group-grant",
            title="Top Group Grant",
            parent=root_directory,
            owner=carol,
        )
        DirectoryPermission.objects.create(
            directory=top_group_grant,
            group=group,
            permission_type=DirectoryPermission.PermissionType.OWNER,
        )
        # An EDIT (not OWNER) grant must NOT confer administer access.
        top_edit_only = Directory.objects.create(
            path="top-edit-only",
            title="Top Edit Only",
            parent=root_directory,
            owner=carol,
        )
        DirectoryPermission.objects.create(
            directory=top_edit_only,
            user=other_user,
            permission_type=DirectoryPermission.PermissionType.EDIT,
        )
        top_unrelated = Directory.objects.create(
            path="top-unrelated",
            title="Top Unrelated",
            parent=root_directory,
            owner=carol,
        )
        return [
            root_directory,
            top_owned_by_other,
            mid_no_grant,
            top_grant,
            mid_inherits_grant,
            top_group_grant,
            top_edit_only,
            top_unrelated,
        ]

    def test_matches_can_administer_directory(
        self, tree, user, other_user, group
    ):
        other_user.groups.add(group)

        for viewer in (AnonymousUser(), user, other_user):
            resolve = _bulk_administer_directory_resolver(viewer)
            for d in tree:
                assert resolve(d.id) == can_administer_directory(viewer, d), (
                    f"resolver disagreed with can_administer_directory for "
                    f"{viewer} on {d.path!r}"
                )

    def test_matches_for_system_owner(self, tree, owner_user):
        resolve = _bulk_administer_directory_resolver(owner_user)
        for d in tree:
            assert resolve(d.id) is True
            assert can_administer_directory(owner_user, d) is True

    def test_query_count_is_flat(self, root_directory, user):
        small_parent = root_directory
        for i in range(2):
            small_parent = Directory.objects.create(
                path=f"small-{i}"
                if small_parent.path == ""
                else f"{small_parent.path}/small-{i}",
                title=f"Small {i}",
                parent=small_parent,
                owner=user,
            )
        with CaptureQueriesContext(connection) as small:
            filter_administerable_directories(
                User.objects.get(pk=user.pk), Directory.objects.all()
            )

        big_parent = root_directory
        for i in range(12):
            big_parent = Directory.objects.create(
                path=f"big-{i}"
                if big_parent.path == ""
                else f"{big_parent.path}/big-{i}",
                title=f"Big {i}",
                parent=big_parent,
                owner=user,
            )
        for i in range(30):
            Directory.objects.create(
                path=f"sib-{i}",
                title=f"Sib {i}",
                parent=root_directory,
                owner=user,
            )
        with CaptureQueriesContext(connection) as big:
            filter_administerable_directories(
                User.objects.get(pk=user.pk), Directory.objects.all()
            )

        assert len(big.captured_queries) == len(small.captured_queries)


class TestCanEditPage:
    def test_owner_can_edit(self, user, page):
        assert can_edit_page(user, page)

    def test_anon_cannot_edit(self, page):
        assert not can_edit_page(AnonymousUser(), page)

    def test_other_user_cannot_edit_by_default(self, other_user, page):
        assert not can_edit_page(other_user, page)

    def test_system_owner_can_edit_any(self, other_user, page):
        SystemConfig.objects.create(owner=other_user)
        assert can_edit_page(other_user, page)

    def test_user_with_edit_permission_can_edit(self, other_user, page):
        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type=PagePermission.PermissionType.EDIT,
        )
        assert can_edit_page(other_user, page)

    def test_group_edit_permission(self, other_user, page, group):
        PagePermission.objects.create(
            page=page,
            group=group,
            permission_type=PagePermission.PermissionType.EDIT,
        )
        assert not can_edit_page(other_user, page)
        other_user.groups.add(group)
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache
        assert can_edit_page(other_user, page)

    def test_directory_group_edit_grants_page_edit(
        self, other_user, user, sub_directory, group
    ):
        p = Page.objects.create(
            title="Dir Edit",
            slug="dir-edit",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        DirectoryPermission.objects.create(
            directory=sub_directory,
            group=group,
            permission_type=DirectoryPermission.PermissionType.EDIT,
        )
        assert not can_edit_page(other_user, p)
        other_user.groups.add(group)
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache
        assert can_edit_page(other_user, p)


class TestCanEditDirectory:
    def test_owner_can_edit(self, user, sub_directory):
        assert can_edit_directory(user, sub_directory)

    def test_anon_cannot_edit(self, sub_directory):
        assert not can_edit_directory(AnonymousUser(), sub_directory)

    def test_system_owner_can_edit(self, other_user, sub_directory):
        SystemConfig.objects.create(owner=other_user)
        assert can_edit_directory(other_user, sub_directory)

    def test_group_edit_permission(self, other_user, sub_directory, group):
        DirectoryPermission.objects.create(
            directory=sub_directory,
            group=group,
            permission_type=DirectoryPermission.PermissionType.EDIT,
        )
        assert not can_edit_directory(other_user, sub_directory)
        other_user.groups.add(group)
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache
        assert can_edit_directory(other_user, sub_directory)


class TestVisibilityGatesEditAccess:
    """Verify that view access is enforced before edit access.

    The core security invariant: a user who cannot VIEW a page or
    directory must NEVER be able to edit it, even if the editability
    setting would otherwise allow it (e.g. editability="internal" on
    a private directory).
    """

    def test_private_dir_internal_edit_denies_non_viewer_page(
        self, user, other_user, private_directory
    ):
        """Page in a private dir with editability=internal: non-viewer
        must not be able to edit."""
        private_directory.editability = "internal"
        private_directory.save()

        page = Page.objects.create(
            title="Secret Roadmap",
            slug="secret-roadmap",
            content="Confidential plans.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )

        # other_user is authenticated but has no access to private dir
        assert not can_view_page(other_user, page)
        assert not can_edit_page(other_user, page)

    def test_private_dir_internal_edit_allows_authorized_viewer(
        self, user, other_user, private_directory
    ):
        """Page in a private dir with editability=internal: user with
        view permission should be able to edit."""
        private_directory.editability = "internal"
        private_directory.save()

        page = Page.objects.create(
            title="Visible Roadmap",
            slug="visible-roadmap",
            content="Plans for those with access.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        DirectoryPermission.objects.create(
            directory=private_directory,
            user=other_user,
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )

        assert can_view_page(other_user, page)
        assert can_edit_page(other_user, page)

    def test_private_dir_internal_edit_denies_non_viewer_directory(
        self, user, other_user, root_directory
    ):
        """Private dir with editability=internal: non-viewer must not
        be able to edit the directory itself."""
        private_dir = Directory.objects.create(
            path="classified",
            title="Classified",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility="private",
            editability="internal",
        )

        assert not can_view_directory(other_user, private_dir)
        assert not can_edit_directory(other_user, private_dir)

    def test_private_dir_internal_edit_allows_authorized_viewer_directory(
        self, user, other_user, root_directory
    ):
        """Private dir with editability=internal: user with view
        permission should be able to edit the directory."""
        private_dir = Directory.objects.create(
            path="team-dir",
            title="Team Dir",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility="private",
            editability="internal",
        )
        DirectoryPermission.objects.create(
            directory=private_dir,
            user=other_user,
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )

        assert can_view_directory(other_user, private_dir)
        assert can_edit_directory(other_user, private_dir)

    def test_private_page_internal_edit_denies_non_viewer(
        self, user, other_user
    ):
        """A directly private page with editability=internal: non-viewer
        must not be able to edit."""
        page = Page.objects.create(
            title="Private Internal",
            slug="private-internal",
            content="Secret.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="private",
            editability="internal",
        )

        assert not can_view_page(other_user, page)
        assert not can_edit_page(other_user, page)

    def test_editable_page_ids_excludes_non_viewable(
        self, user, other_user, private_directory
    ):
        """editable_page_ids must not include pages the user cannot view."""
        private_directory.editability = "internal"
        private_directory.save()

        page = Page.objects.create(
            title="Hidden Page",
            slug="hidden-page",
            content="Cannot see this.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )

        ids = editable_page_ids(other_user)
        assert page.id not in ids


class TestVisibilityGatesEditViews:
    """Verify that edit/move/permissions/revert views return 404 for
    users who cannot view the page or directory, even when editability
    would otherwise grant access."""

    def test_page_edit_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Page",
            slug="secret-page-edit",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        client.force_login(other_user)
        url = reverse("page_edit", kwargs={"path": page.content_path})
        response = client.get(url)
        assert response.status_code == 404

    def test_page_move_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Move",
            slug="secret-page-move",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        client.force_login(other_user)
        url = reverse("page_move", kwargs={"path": page.content_path})
        response = client.get(url)
        assert response.status_code == 404

    def test_page_permissions_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Perms",
            slug="secret-page-perms",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        client.force_login(other_user)
        url = reverse("page_permissions", kwargs={"path": page.content_path})
        response = client.get(url)
        assert response.status_code == 404

    def test_directory_edit_returns_404_for_non_viewer(
        self, client, user, other_user, root_directory
    ):
        private_dir = Directory.objects.create(
            path="secret-dir-edit",
            title="Secret Dir",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility="private",
            editability="internal",
        )
        client.force_login(other_user)
        url = reverse("directory_edit", kwargs={"path": private_dir.path})
        response = client.get(url)
        assert response.status_code == 404

    def test_directory_delete_returns_404_for_non_viewer(
        self, client, user, other_user, root_directory
    ):
        private_dir = Directory.objects.create(
            path="secret-dir-del",
            title="Secret Dir Del",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility="private",
            editability="internal",
        )
        client.force_login(other_user)
        url = reverse("directory_delete", kwargs={"path": private_dir.path})
        response = client.get(url)
        assert response.status_code == 404

    def test_directory_permissions_returns_404_for_non_viewer(
        self, client, user, other_user, root_directory
    ):
        private_dir = Directory.objects.create(
            path="secret-dir-perms",
            title="Secret Dir Perms",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility="private",
            editability="internal",
        )
        client.force_login(other_user)
        url = reverse(
            "directory_permissions",
            kwargs={"path": private_dir.path},
        )
        response = client.get(url)
        assert response.status_code == 404

    def test_page_delete_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Delete",
            slug="secret-page-del",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        client.force_login(other_user)
        url = reverse("page_delete", kwargs={"path": page.content_path})
        response = client.get(url)
        assert response.status_code == 404

    def test_page_revert_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Revert",
            slug="secret-page-rev",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message="v1",
            revision_number=1,
            created_by=user,
        )
        client.force_login(other_user)
        url = reverse(
            "page_revert",
            kwargs={"path": page.content_path, "rev_num": 1},
        )
        response = client.get(url)
        assert response.status_code == 404

    def test_proposal_list_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Proposals",
            slug="secret-page-prop",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        client.force_login(other_user)
        url = reverse("proposal_list", kwargs={"path": page.content_path})
        response = client.get(url)
        assert response.status_code == 404

    def test_proposal_review_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Review",
            slug="secret-page-review",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_title=page.title,
            proposed_content="New content",
            change_message="test",
        )
        client.force_login(other_user)
        url = reverse(
            "proposal_review",
            kwargs={"path": page.content_path, "pk": proposal.pk},
        )
        response = client.get(url)
        assert response.status_code == 404

    def test_proposal_accept_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Accept",
            slug="secret-page-accept",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_title=page.title,
            proposed_content="New content",
            change_message="test",
        )
        client.force_login(other_user)
        url = reverse(
            "proposal_accept",
            kwargs={"path": page.content_path, "pk": proposal.pk},
        )
        response = client.post(url)
        assert response.status_code == 404

    def test_proposal_deny_returns_404_for_non_viewer(
        self, client, user, other_user, private_directory
    ):
        private_directory.editability = "internal"
        private_directory.save()
        page = Page.objects.create(
            title="Secret Deny",
            slug="secret-page-deny",
            content="Hidden.",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="inherit",
            editability="inherit",
        )
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_title=page.title,
            proposed_content="New content",
            change_message="test",
        )
        client.force_login(other_user)
        url = reverse(
            "proposal_deny",
            kwargs={"path": page.content_path, "pk": proposal.pk},
        )
        response = client.post(url)
        assert response.status_code == 404


# ── Edit Lock Helpers ─────────────────────────────────────


class TestEditLockPage:
    def test_acquire_creates_lock(self, user, page):
        lock = acquire_lock_for_page(page, user)
        assert lock.page == page
        assert lock.user == user
        assert lock.expires_at > timezone.now()

    def test_acquire_replaces_existing_lock(self, user, other_user, page):
        acquire_lock_for_page(page, user)
        acquire_lock_for_page(page, other_user)
        assert EditLock.objects.filter(page=page).count() == 1
        assert EditLock.objects.get(page=page).user == other_user

    def test_get_active_lock(self, user, other_user, page):
        acquire_lock_for_page(page, user)
        lock = get_active_lock_for_page(page, exclude_user=other_user)
        assert lock is not None
        assert lock.user == user

    def test_get_active_lock_excludes_self(self, user, page):
        acquire_lock_for_page(page, user)
        lock = get_active_lock_for_page(page, exclude_user=user)
        assert lock is None

    def test_expired_lock_not_returned(self, user, other_user, page):
        acquire_lock_for_page(page, user)
        future = timezone.now() + EditLock.LOCK_DURATION * 2
        with time_machine.travel(future, tick=False):
            lock = get_active_lock_for_page(page, exclude_user=other_user)
            assert lock is None

    def test_release_lock(self, user, page):
        acquire_lock_for_page(page, user)
        release_lock_for_page(page)
        assert not EditLock.objects.filter(page=page).exists()


class TestEditLockDirectory:
    def test_acquire_creates_lock(self, user, sub_directory):
        lock = acquire_lock_for_directory(sub_directory, user)
        assert lock.directory == sub_directory
        assert lock.user == user

    def test_acquire_replaces_existing_lock(
        self, user, other_user, sub_directory
    ):
        acquire_lock_for_directory(sub_directory, user)
        acquire_lock_for_directory(sub_directory, other_user)
        assert EditLock.objects.filter(directory=sub_directory).count() == 1
        assert EditLock.objects.get(directory=sub_directory).user == other_user

    def test_get_active_lock(self, user, other_user, sub_directory):
        acquire_lock_for_directory(sub_directory, user)
        lock = get_active_lock_for_directory(
            sub_directory, exclude_user=other_user
        )
        assert lock is not None
        assert lock.user == user

    def test_get_active_lock_excludes_self(self, user, sub_directory):
        acquire_lock_for_directory(sub_directory, user)
        lock = get_active_lock_for_directory(sub_directory, exclude_user=user)
        assert lock is None

    def test_expired_lock_not_returned(self, user, other_user, sub_directory):
        acquire_lock_for_directory(sub_directory, user)
        future = timezone.now() + EditLock.LOCK_DURATION * 2
        with time_machine.travel(future, tick=False):
            lock = get_active_lock_for_directory(
                sub_directory, exclude_user=other_user
            )
            assert lock is None

    def test_release_lock(self, user, sub_directory):
        acquire_lock_for_directory(sub_directory, user)
        release_lock_for_directory(sub_directory)
        assert not EditLock.objects.filter(directory=sub_directory).exists()


class TestCleanupExpiredLocks:
    def test_cleanup_deletes_expired(self, user, page):
        acquire_lock_for_page(page, user)
        future = timezone.now() + EditLock.LOCK_DURATION * 2
        with time_machine.travel(future, tick=False):
            count = cleanup_expired_locks()
            assert count == 1
            assert not EditLock.objects.filter(page=page).exists()

    def test_cleanup_preserves_active(self, user, page):
        acquire_lock_for_page(page, user)
        count = cleanup_expired_locks()
        assert count == 0
        assert EditLock.objects.filter(page=page).exists()
