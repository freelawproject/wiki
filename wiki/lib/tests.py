"""Tests for shared lib: permissions, markdown, storage, edit locks."""

import time_machine
from django.contrib.auth.models import AnonymousUser
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
    can_edit_directory,
    can_edit_page,
    can_view_directory,
    can_view_page,
    editable_page_ids,
    is_system_owner,
)
from wiki.pages.models import Page, PagePermission
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
