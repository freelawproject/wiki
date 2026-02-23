"""Tests for shared lib: permissions, markdown, storage, edit locks."""

import time_machine
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

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
    can_view_page,
    is_system_owner,
)
from wiki.pages.models import Page, PagePermission


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
        from wiki.users.models import SystemConfig

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
        from wiki.directories.models import DirectoryPermission

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
        from wiki.directories.models import DirectoryPermission

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
        from wiki.users.models import SystemConfig

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
        from wiki.directories.models import DirectoryPermission

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
        from wiki.users.models import SystemConfig

        SystemConfig.objects.create(owner=other_user)
        assert can_edit_directory(other_user, sub_directory)

    def test_group_edit_permission(self, other_user, sub_directory, group):
        from wiki.directories.models import DirectoryPermission

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
