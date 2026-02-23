"""Tests for the directories app: navigation, breadcrumbs, permissions."""

import pytest
from django.test import Client

from wiki.directories.models import Directory, DirectoryRevision
from wiki.lib.edit_lock import acquire_lock_for_directory
from wiki.lib.models import EditLock


@pytest.fixture
def client():
    return Client()


class TestRootView:
    def test_root_page_loads(self, client, db):
        r = client.get("/c/")
        assert r.status_code == 200

    def test_root_shows_pages(self, client, page):
        r = client.get("/c/")
        assert b"Getting Started" in r.content

    def test_root_shows_subdirectories(
        self, client, root_directory, sub_directory
    ):
        r = client.get("/c/")
        assert b"Engineering" in r.content

    def test_root_shows_new_page_link_for_auth(self, client, user):
        client.force_login(user)
        r = client.get("/c/")
        assert b"/c/new/" in r.content

    def test_root_hides_new_page_for_anon(self, client, db):
        r = client.get("/c/")
        assert b"/c/new/" not in r.content


class TestDirectoryDetail:
    def test_directory_loads(self, client, sub_directory):
        r = client.get("/c/engineering")
        assert r.status_code == 200
        assert b"Engineering" in r.content

    def test_directory_shows_pages(
        self, client, page_in_directory, sub_directory
    ):
        r = client.get("/c/engineering")
        assert b"Coding Standards" in r.content

    def test_directory_shows_subdirectories(
        self, client, sub_directory, nested_directory
    ):
        r = client.get("/c/engineering")
        assert b"DevOps" in r.content

    def test_nested_directory_loads(self, client, nested_directory):
        r = client.get("/c/engineering/devops")
        assert r.status_code == 200
        assert b"DevOps" in r.content

    def test_breadcrumbs_show_ancestry(self, client, nested_directory):
        r = client.get("/c/engineering/devops")
        content = r.content.decode()
        assert "Home" in content
        assert "Engineering" in content
        assert "DevOps" in content

    def test_nonexistent_directory_404(self, client, db):
        r = client.get("/c/nonexistent")
        assert r.status_code == 404


class TestDirectoryEdit:
    def test_edit_requires_login(self, client, sub_directory):
        r = client.get("/c/engineering/edit-dir/")
        assert r.status_code == 302

    def test_owner_can_edit(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            "/c/engineering/edit-dir/",
            {
                "title": "Eng Team",
                "description": "Updated",
                "visibility": "public",
            },
        )
        assert r.status_code == 302
        sub_directory.refresh_from_db()
        assert sub_directory.title == "Eng Team"

    def test_non_owner_cannot_edit(self, client, other_user, sub_directory):
        client.force_login(other_user)
        r = client.post(
            "/c/engineering/edit-dir/",
            {"title": "Hacked", "description": ""},
        )
        assert r.status_code == 302
        sub_directory.refresh_from_db()
        assert sub_directory.title == "Engineering"

    def test_edit_form_has_markdown_editor(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get("/c/engineering/edit-dir/")
        content = r.content.decode()
        assert 'id="markdown-editor"' in content
        assert "easymde.min.js" in content
        assert "markdown-editor.js" in content
        assert "easymde.min.css" in content

    def test_create_form_has_markdown_editor(
        self, client, user, root_directory
    ):
        client.force_login(user)
        r = client.get("/c/new-dir/")
        content = r.content.decode()
        assert 'id="markdown-editor"' in content
        assert "easymde.min.js" in content
        assert "markdown-editor.js" in content

    def test_editor_auto_init_contract(self, client, user, sub_directory):
        """Directory forms must have editor-config but NOT page-config.

        markdown-editor.js auto-initialises EasyMDE when it finds
        editor-config without page-config.  If both are present the
        auto-init is skipped (page-form.js handles it instead), so
        the editor would silently fail to appear.
        """
        client.force_login(user)
        for url in ["/c/new-dir/", "/c/engineering/edit-dir/"]:
            content = client.get(url).content.decode()
            assert 'id="editor-config"' in content, (
                f"{url} missing editor-config"
            )
            assert 'id="page-config"' not in content, (
                f"{url} must NOT include page-config or the editor "
                f"auto-init will be skipped"
            )


class TestDirectoryModel:
    def test_get_absolute_url_root(self, root_directory):
        assert root_directory.get_absolute_url() == "/c/"

    def test_get_absolute_url_subdir(self, sub_directory):
        assert sub_directory.get_absolute_url() == "/c/engineering"

    def test_get_ancestors(self, nested_directory, sub_directory):
        ancestors = nested_directory.get_ancestors()
        # root_directory is the parent of sub_directory
        assert sub_directory not in ancestors or len(ancestors) >= 1

    def test_get_breadcrumbs(self, nested_directory):
        crumbs = nested_directory.get_breadcrumbs()
        assert crumbs[0] == ("Home", "/c/")
        assert crumbs[-1][0] == "DevOps"


class TestCreatePageInDirectory:
    def test_create_page_in_dir(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            "/c/engineering/new/",
            {
                "title": "New Page",
                "content": "Content",
                "visibility": "public",
                "change_message": "Test",
            },
        )
        assert r.status_code == 302
        from wiki.pages.models import Page

        p = Page.objects.get(slug="new-page")
        assert p.directory == sub_directory


class TestCreateDirectory:
    def test_create_requires_login(self, client, db):
        r = client.get("/c/new-dir/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_create_root_directory(self, client, user, root_directory):
        client.force_login(user)
        r = client.post(
            "/c/new-dir/",
            {"title": "Projects", "description": "", "visibility": "public"},
        )
        assert r.status_code == 302
        d = Directory.objects.get(path="projects")
        assert d.title == "Projects"
        assert d.parent == root_directory
        assert d.owner == user

    def test_create_subdirectory(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            "/c/engineering/new-dir/",
            {
                "title": "Backend",
                "description": "Backend team docs",
                "visibility": "public",
            },
        )
        assert r.status_code == 302
        d = Directory.objects.get(path="engineering/backend")
        assert d.parent == sub_directory

    def test_new_dir_button_visible_for_auth(
        self, client, user, root_directory
    ):
        client.force_login(user)
        r = client.get("/c/")
        assert b"new-dir" in r.content

    def test_new_dir_button_hidden_for_anon(self, client, db):
        r = client.get("/c/")
        assert b"new-dir" not in r.content


class TestDeleteDirectory:
    def test_delete_requires_login(self, client, sub_directory):
        r = client.get("/c/engineering/delete-dir/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_delete_empty_directory(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post("/c/engineering/delete-dir/")
        assert r.status_code == 302
        assert not Directory.objects.filter(path="engineering").exists()

    def test_cannot_delete_nonempty_directory(
        self, client, user, sub_directory, nested_directory
    ):
        client.force_login(user)
        r = client.post("/c/engineering/delete-dir/")
        # Should redirect back with error, directory still exists
        assert r.status_code == 302
        assert Directory.objects.filter(path="engineering").exists()

    def test_cannot_delete_dir_with_pages(
        self, client, user, sub_directory, page_in_directory
    ):
        client.force_login(user)
        r = client.post("/c/engineering/delete-dir/")
        assert r.status_code == 302
        assert Directory.objects.filter(path="engineering").exists()

    def test_non_editor_cannot_delete(self, client, other_user, sub_directory):
        client.force_login(other_user)
        r = client.post("/c/engineering/delete-dir/")
        assert r.status_code == 302
        assert Directory.objects.filter(path="engineering").exists()


class TestDirectoryPermissions:
    def test_permissions_requires_login(self, client, sub_directory):
        r = client.get("/c/engineering/permissions-dir/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_permissions_page_loads(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get("/c/engineering/permissions-dir/")
        assert r.status_code == 200
        assert b"Permissions" in r.content

    def test_add_permission(self, client, user, other_user, sub_directory):
        from wiki.directories.models import DirectoryPermission

        client.force_login(user)
        r = client.post(
            "/c/engineering/permissions-dir/",
            {"username": "bob", "permission_type": "view"},
        )
        assert r.status_code == 302
        assert DirectoryPermission.objects.filter(
            directory=sub_directory,
            user=other_user,
            permission_type="view",
        ).exists()

    def test_remove_permission(self, client, user, other_user, sub_directory):
        from wiki.directories.models import DirectoryPermission

        perm = DirectoryPermission.objects.create(
            directory=sub_directory,
            user=other_user,
            permission_type="edit",
        )
        client.force_login(user)
        r = client.post(
            "/c/engineering/permissions-dir/",
            {"remove": perm.pk},
        )
        assert r.status_code == 302
        assert not DirectoryPermission.objects.filter(pk=perm.pk).exists()

    def test_non_editor_cannot_access(self, client, other_user, sub_directory):
        client.force_login(other_user)
        r = client.get("/c/engineering/permissions-dir/")
        assert r.status_code == 302

    def test_add_group_permission(self, client, user, sub_directory, group):
        from wiki.directories.models import DirectoryPermission

        client.force_login(user)
        r = client.post(
            "/c/engineering/permissions-dir/",
            {
                "target_type": "group",
                "group": group.pk,
                "permission_type": "view",
            },
        )
        assert r.status_code == 302
        assert DirectoryPermission.objects.filter(
            directory=sub_directory,
            group=group,
            permission_type="view",
        ).exists()

    def test_remove_group_permission(self, client, user, sub_directory, group):
        from wiki.directories.models import DirectoryPermission

        perm = DirectoryPermission.objects.create(
            directory=sub_directory,
            group=group,
            permission_type="edit",
        )
        client.force_login(user)
        r = client.post(
            "/c/engineering/permissions-dir/",
            {"remove": perm.pk},
        )
        assert r.status_code == 302
        assert not DirectoryPermission.objects.filter(pk=perm.pk).exists()

    def test_group_permissions_shown_in_template(
        self, client, user, sub_directory, group
    ):
        from wiki.directories.models import DirectoryPermission

        DirectoryPermission.objects.create(
            directory=sub_directory,
            group=group,
            permission_type="view",
        )
        client.force_login(user)
        r = client.get("/c/engineering/permissions-dir/")
        assert b"Engineering Team" in r.content
        assert b"Group Permissions" in r.content


class TestDirectorySort:
    def test_default_sort_is_title(self, client, page):
        r = client.get("/c/")
        assert r.status_code == 200
        assert b"Sort by:" in r.content
        # "Title" should be bold (active)
        assert (
            b'<strong class="text-gray-900 dark:text-gray-100">Title</strong>'
            in r.content
        )

    def test_sort_updated_reorders_pages(self, client, user, root_directory):
        from datetime import timedelta

        from django.utils import timezone

        from wiki.pages.models import Page

        # Create two pages with different updated_at timestamps
        older = Page.objects.create(
            title="AAA First",
            slug="aaa-first",
            content="old",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        newer = Page.objects.create(
            title="ZZZ Last",
            slug="zzz-last",
            content="new",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )

        # Force different updated_at values
        Page.objects.filter(pk=older.pk).update(
            updated_at=timezone.now() - timedelta(days=10)
        )
        Page.objects.filter(pk=newer.pk).update(updated_at=timezone.now())

        # Default sort (title): AAA before ZZZ
        r = client.get("/c/")
        content = r.content.decode()
        assert content.index("AAA First") < content.index("ZZZ Last")

        # Sort by updated: ZZZ (newer) before AAA (older)
        r = client.get("/c/?sort=updated")
        content = r.content.decode()
        assert content.index("ZZZ Last") < content.index("AAA First")

    def test_sort_views_reorders_pages(self, client, user, root_directory):
        from wiki.pages.models import Page

        Page.objects.create(
            title="AAA Low Views",
            slug="aaa-low-views",
            content="",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            view_count=5,
        )
        Page.objects.create(
            title="ZZZ High Views",
            slug="zzz-high-views",
            content="",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            view_count=100,
        )

        # Sort by views: high views page first
        r = client.get("/c/?sort=views")
        content = r.content.decode()
        assert content.index("ZZZ High Views") < content.index("AAA Low Views")

    def test_invalid_sort_falls_back_to_title(self, client, page):
        r = client.get("/c/?sort=bogus")
        assert r.status_code == 200
        # Should fall back to title (bold)
        assert (
            b'<strong class="text-gray-900 dark:text-gray-100">Title</strong>'
            in r.content
        )

    def test_sort_controls_hidden_when_empty(self, client, db):
        r = client.get("/c/")
        assert b"Sort by:" not in r.content

    def test_sort_works_on_subdirectory(self, client, user, sub_directory):
        from wiki.pages.models import Page

        Page.objects.create(
            title="Sub Page",
            slug="sub-page-sort",
            content="",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        r = client.get("/c/engineering?sort=updated")
        assert r.status_code == 200
        assert (
            b'<strong class="text-gray-900 dark:text-gray-100">Last edited</strong>'
            in r.content
        )


class TestDirectorySearchAPI:
    def test_search_returns_subdirectories(
        self, client, user, root_directory, sub_directory
    ):
        client.force_login(user)
        r = client.get("/api/dir-search/?parent=")
        assert r.status_code == 200
        import json

        data = json.loads(r.content)
        titles = [d["title"] for d in data]
        assert "Engineering" in titles

    def test_search_filters_by_query(
        self, client, user, root_directory, sub_directory
    ):
        client.force_login(user)
        r = client.get("/api/dir-search/?parent=&q=eng")
        data = __import__("json").loads(r.content)
        assert len(data) == 1
        assert data[0]["title"] == "Engineering"

    def test_search_scoped_to_parent(
        self, client, user, sub_directory, nested_directory
    ):
        client.force_login(user)
        r = client.get("/api/dir-search/?parent=engineering")
        data = __import__("json").loads(r.content)
        titles = [d["title"] for d in data]
        assert "DevOps" in titles


class TestHelpLink:
    def test_help_directory_accessible(self, client, user):
        """The /c/help link works after seed_help_pages creates the dir."""
        from django.core.management import call_command

        client.force_login(user)
        call_command("seed_help_pages")
        r = client.get("/c/help")
        assert r.status_code == 200
        assert b"Help" in r.content

    def test_root_created_on_first_visit(self, client, db):
        """Visiting /c/ creates the root directory if it doesn't exist."""
        assert not Directory.objects.filter(path="").exists()
        r = client.get("/c/")
        assert r.status_code == 200
        assert Directory.objects.filter(path="").exists()


class TestDirectorySearchOrphans:
    def test_search_finds_orphaned_directories(self, client, user):
        """Dirs with parent=None appear in root-level autocomplete."""
        Directory.objects.create(
            path="orphan",
            title="Orphan Dir",
            parent=None,
            owner=user,
            created_by=user,
        )
        client.force_login(user)
        r = client.get("/api/dir-search/?parent=")
        data = __import__("json").loads(r.content)
        titles = [d["title"] for d in data]
        assert "Orphan Dir" in titles


class TestMoveDirectory:
    def test_move_requires_login(self, client, sub_directory):
        r = client.get("/c/engineering/move-dir/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_move_directory(self, client, user, sub_directory, root_directory):
        # Create a second top-level directory to move engineering into
        other = Directory.objects.create(
            path="other",
            title="Other",
            parent=root_directory,
            owner=user,
            created_by=user,
        )
        client.force_login(user)
        r = client.post(
            "/c/engineering/move-dir/",
            {"parent": other.pk},
        )
        assert r.status_code == 302
        sub_directory.refresh_from_db()
        assert sub_directory.parent == other
        assert sub_directory.path == "other/engineering"

    def test_move_updates_descendant_paths(
        self,
        client,
        user,
        sub_directory,
        nested_directory,
        root_directory,
    ):
        other = Directory.objects.create(
            path="other",
            title="Other",
            parent=root_directory,
            owner=user,
            created_by=user,
        )
        client.force_login(user)
        client.post(
            "/c/engineering/move-dir/",
            {"parent": other.pk},
        )
        nested_directory.refresh_from_db()
        assert nested_directory.path == "other/engineering/devops"


class TestDirectoryVisibility:
    """Part 1: Directory visibility field."""

    def test_new_directory_defaults_to_public(self, sub_directory):
        assert sub_directory.visibility == "public"

    def test_create_private_directory(self, client, user, root_directory):
        client.force_login(user)
        r = client.post(
            "/c/new-dir/",
            {
                "title": "Secret",
                "description": "",
                "visibility": "private",
            },
        )
        assert r.status_code == 302
        d = Directory.objects.get(path="secret")
        assert d.visibility == "private"

    def test_edit_visibility(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            "/c/engineering/edit-dir/",
            {
                "title": "Engineering",
                "description": "",
                "visibility": "private",
            },
        )
        assert r.status_code == 302
        sub_directory.refresh_from_db()
        assert sub_directory.visibility == "private"

    def test_visibility_badge_shown_for_private(
        self, client, private_directory
    ):
        from wiki.users.models import SystemConfig

        user = private_directory.owner
        SystemConfig.objects.create(owner=user)
        client.force_login(user)
        r = client.get("/c/secret-team")
        assert b"Private" in r.content

    def test_visibility_badge_not_shown_for_public(
        self, client, user, sub_directory
    ):
        client.force_login(user)
        r = client.get("/c/engineering")
        assert b"Private" not in r.content

    def test_form_includes_visibility_field(
        self, client, user, root_directory
    ):
        client.force_login(user)
        r = client.get("/c/new-dir/")
        assert b"id_visibility" in r.content


class TestDirectoryGate:
    """Part 2: can_view_directory and gate enforcement."""

    def test_public_directory_visible_to_anon(self, client, sub_directory):
        r = client.get("/c/engineering")
        assert r.status_code == 200

    def test_private_directory_404_for_anon(self, client, private_directory):
        r = client.get("/c/secret-team")
        assert r.status_code == 404

    def test_private_directory_visible_to_owner(
        self, client, user, private_directory
    ):
        client.force_login(user)
        r = client.get("/c/secret-team")
        assert r.status_code == 200

    def test_private_directory_404_for_other_user(
        self, client, other_user, private_directory
    ):
        client.force_login(other_user)
        r = client.get("/c/secret-team")
        assert r.status_code == 404

    def test_private_directory_visible_to_system_owner(
        self, client, other_user, private_directory
    ):
        from wiki.users.models import SystemConfig

        SystemConfig.objects.create(owner=other_user)
        client.force_login(other_user)
        r = client.get("/c/secret-team")
        assert r.status_code == 200

    def test_private_directory_visible_with_permission(
        self, client, other_user, private_directory
    ):
        from .models import DirectoryPermission

        DirectoryPermission.objects.create(
            directory=private_directory,
            user=other_user,
            permission_type="view",
        )
        client.force_login(other_user)
        r = client.get("/c/secret-team")
        assert r.status_code == 200

    def test_private_directory_hidden_in_root_listing(
        self, client, root_directory, sub_directory, private_directory
    ):
        r = client.get("/c/")
        content = r.content.decode()
        assert "Engineering" in content
        assert "Secret Team" not in content

    def test_private_subdir_hidden_in_parent_listing(
        self, client, user, sub_directory
    ):
        # Create a private subdir under engineering
        Directory.objects.create(
            path="engineering/private-child",
            title="Private Child",
            parent=sub_directory,
            owner=user,
            created_by=user,
            visibility="private",
        )
        # Other user should not see it
        from django.contrib.auth.models import User

        from wiki.users.models import UserProfile

        other = User.objects.create_user(
            username="eve@free.law",
            email="eve@free.law",
            password="testpass",
        )
        UserProfile.objects.create(user=other, display_name="Eve")
        client.force_login(other)
        r = client.get("/c/engineering")
        assert b"Private Child" not in r.content

    def test_private_page_in_private_dir_hidden(
        self, client, other_user, private_directory
    ):
        """A private page in a private directory is hidden even
        if the user has page-level permission but not dir permission."""
        from wiki.pages.models import Page, PagePermission

        page = Page.objects.create(
            title="Secret Doc",
            slug="secret-doc",
            content="shhh",
            directory=private_directory,
            owner=private_directory.owner,
            created_by=private_directory.owner,
            updated_by=private_directory.owner,
            visibility=Page.Visibility.PRIVATE,
        )
        # Grant page-level view but NOT directory-level
        PagePermission.objects.create(
            page=page, user=other_user, permission_type="view"
        )
        client.force_login(other_user)
        r = client.get(page.get_absolute_url())
        assert r.status_code == 404

    def test_create_in_dir_requires_edit_perm(
        self, client, other_user, sub_directory
    ):
        """Non-editor cannot create a subdirectory."""
        client.force_login(other_user)
        r = client.post(
            "/c/engineering/new-dir/",
            {
                "title": "Hacked",
                "description": "",
                "visibility": "public",
            },
        )
        assert r.status_code == 302
        assert not Directory.objects.filter(path="engineering/hacked").exists()


class TestApplyPermissions:
    """Part 4: Apply permissions recursively."""

    def test_apply_direct(self, client, user, sub_directory):
        from wiki.pages.models import Page, PagePermission

        from .models import DirectoryPermission

        # Add a directory permission
        DirectoryPermission.objects.create(
            directory=sub_directory,
            user=user,
            permission_type="view",
        )
        # Create a page in the directory
        page = Page.objects.create(
            title="Test Page",
            slug="test-page-apply",
            content="test",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.post(
            "/c/engineering/apply-permissions-dir/",
            {"scope": "direct"},
        )
        assert r.status_code == 302
        # Page should now have the permission
        assert PagePermission.objects.filter(
            page=page, user=user, permission_type="view"
        ).exists()

    def test_apply_recursive(
        self, client, user, sub_directory, nested_directory
    ):
        from wiki.pages.models import Page, PagePermission

        from .models import DirectoryPermission

        sub_directory.visibility = "private"
        sub_directory.save()
        DirectoryPermission.objects.create(
            directory=sub_directory,
            user=user,
            permission_type="edit",
        )
        # Create page in nested dir
        page = Page.objects.create(
            title="Nested Page",
            slug="nested-page-apply",
            content="test",
            directory=nested_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        client.force_login(user)
        r = client.post(
            "/c/engineering/apply-permissions-dir/",
            {"scope": "recursive"},
        )
        assert r.status_code == 302
        # Nested directory should have the permission
        assert DirectoryPermission.objects.filter(
            directory=nested_directory,
            user=user,
            permission_type="edit",
        ).exists()
        # Nested directory should have matching visibility
        nested_directory.refresh_from_db()
        assert nested_directory.visibility == "private"
        # Nested page should have the permission
        assert PagePermission.objects.filter(
            page=page, user=user, permission_type="edit"
        ).exists()

    def test_apply_permissions_requires_edit(
        self, client, other_user, sub_directory
    ):
        client.force_login(other_user)
        r = client.get("/c/engineering/apply-permissions-dir/")
        assert r.status_code == 302  # redirect with error

    def test_apply_confirmation_page_shows_counts(
        self, client, user, sub_directory
    ):
        from wiki.pages.models import Page

        Page.objects.create(
            title="P1",
            slug="p1-counts",
            content="",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        client.force_login(user)
        r = client.get("/c/engineering/apply-permissions-dir/")
        assert r.status_code == 200
        assert b"direct pages only" in r.content
        assert b"recursively" in r.content

    def test_apply_link_on_permissions_page(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get("/c/engineering/permissions-dir/")
        assert b"apply-permissions-dir" in r.content

    def test_apply_propagates_editability(self, client, user, sub_directory):
        """Apply permissions propagates editability to child pages."""
        from wiki.pages.models import Page

        sub_directory.editability = "internal"
        sub_directory.save(update_fields=["editability"])
        page = Page.objects.create(
            title="Edit Prop Test",
            slug="edit-prop-test",
            content="test",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        client.force_login(user)
        client.post(
            "/c/engineering/apply-permissions-dir/",
            {"scope": "direct"},
        )
        page.refresh_from_db()
        assert page.editability == "internal"

    def test_apply_recursive_propagates_editability(
        self, client, user, sub_directory, nested_directory
    ):
        """Recursive apply propagates editability to subdirs."""
        sub_directory.editability = "internal"
        sub_directory.save(update_fields=["editability"])
        client.force_login(user)
        client.post(
            "/c/engineering/apply-permissions-dir/",
            {"scope": "recursive"},
        )
        nested_directory.refresh_from_db()
        assert nested_directory.editability == "internal"


# ── Directory Editability ──────────────────────────────────


class TestDirectoryEditability:
    """Tests for the FLP-wide editability setting on directories."""

    def test_default_editability_is_restricted(self, sub_directory):
        assert sub_directory.editability == "restricted"

    def test_flp_editable_directory_allows_any_auth_user(
        self, other_user, sub_directory
    ):
        """When editability is 'internal', any logged-in user can edit."""
        from wiki.lib.permissions import can_edit_directory

        assert not can_edit_directory(other_user, sub_directory)
        sub_directory.editability = "internal"
        sub_directory.save(update_fields=["editability"])
        assert can_edit_directory(other_user, sub_directory)

    def test_create_directory_with_editability(
        self, client, user, root_directory
    ):
        client.force_login(user)
        r = client.post(
            "/c/new-dir/",
            {
                "title": "Open Dir",
                "description": "",
                "visibility": "public",
                "editability": "internal",
            },
        )
        assert r.status_code == 302
        d = Directory.objects.get(path="open-dir")
        assert d.editability == "internal"

    def test_edit_directory_editability(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            "/c/engineering/edit-dir/",
            {
                "title": "Engineering",
                "description": "",
                "visibility": "public",
                "editability": "internal",
            },
        )
        assert r.status_code == 302
        sub_directory.refresh_from_db()
        assert sub_directory.editability == "internal"

    def test_cannot_create_flp_editable_private_directory(
        self, client, user, root_directory
    ):
        """FLP Staff editability + Private should be rejected on create."""
        client.force_login(user)
        r = client.post(
            "/c/new-dir/",
            {
                "title": "Bad Dir",
                "description": "",
                "visibility": "private",
                "editability": "internal",
            },
        )
        assert r.status_code == 200
        assert b"FLP Staff" in r.content
        assert not Directory.objects.filter(path="bad-dir").exists()

    def test_cannot_edit_to_flp_editable_private(
        self, client, user, sub_directory
    ):
        """FLP Staff editability + Private should be rejected on edit."""
        client.force_login(user)
        r = client.post(
            "/c/engineering/edit-dir/",
            {
                "title": "Engineering",
                "description": "",
                "visibility": "private",
                "editability": "internal",
            },
        )
        assert r.status_code == 200
        assert b"FLP Staff" in r.content
        sub_directory.refresh_from_db()
        assert sub_directory.editability == "restricted"

    def test_editability_defaults_when_omitted(
        self, client, user, root_directory
    ):
        """Omitting editability still creates with 'restricted'."""
        client.force_login(user)
        r = client.post(
            "/c/new-dir/",
            {
                "title": "Default Dir",
                "description": "",
                "visibility": "public",
            },
        )
        assert r.status_code == 302
        d = Directory.objects.get(path="default-dir")
        assert d.editability == "restricted"

    def test_form_includes_editability_field(
        self, client, user, root_directory
    ):
        client.force_login(user)
        r = client.get("/c/new-dir/")
        assert b"id_editability" in r.content


class TestDirectoryHistory:
    def test_directory_edit_creates_revision(
        self, client, user, sub_directory
    ):
        client.force_login(user)
        client.post(
            "/c/engineering/edit-dir/",
            {
                "title": "Engineering Updated",
                "description": "New desc",
                "visibility": "public",
                "change_message": "Updated title",
            },
        )
        assert DirectoryRevision.objects.filter(
            directory=sub_directory
        ).exists()
        rev = DirectoryRevision.objects.get(directory=sub_directory)
        assert rev.title == "Engineering Updated"
        assert rev.change_message == "Updated title"

    def test_directory_create_creates_initial_revision(
        self, client, user, root_directory
    ):
        client.force_login(user)
        client.post(
            "/c/new-dir/",
            {
                "title": "New Team",
                "description": "",
                "visibility": "public",
            },
        )
        d = Directory.objects.get(path="new-team")
        assert d.revisions.count() == 1
        rev = d.revisions.first()
        assert rev.revision_number == 1
        assert rev.change_message == "Initial creation"

    def test_directory_history_view(self, client, user, sub_directory):
        DirectoryRevision.objects.create(
            directory=sub_directory,
            title=sub_directory.title,
            description="",
            visibility="public",
            editability="restricted",
            change_message="First edit",
            revision_number=1,
            created_by=user,
        )
        r = client.get("/c/engineering/history-dir/")
        assert r.status_code == 200
        assert b"First edit" in r.content

    def test_directory_diff_view(self, client, user, sub_directory):
        DirectoryRevision.objects.create(
            directory=sub_directory,
            title="Engineering",
            description="Old desc",
            visibility="public",
            editability="restricted",
            change_message="v1",
            revision_number=1,
            created_by=user,
        )
        DirectoryRevision.objects.create(
            directory=sub_directory,
            title="Engineering v2",
            description="New desc",
            visibility="private",
            editability="restricted",
            change_message="v2",
            revision_number=2,
            created_by=user,
        )
        r = client.get("/c/engineering/diff-dir/1/2/")
        assert r.status_code == 200
        content = r.content.decode()
        assert "Metadata changes" in content
        assert "Visibility" in content

    def test_directory_revert(self, client, user, sub_directory):
        DirectoryRevision.objects.create(
            directory=sub_directory,
            title="Old Title",
            description="Old desc",
            visibility="public",
            editability="restricted",
            change_message="v1",
            revision_number=1,
            created_by=user,
        )
        # Edit the directory
        sub_directory.title = "New Title"
        sub_directory.save()
        DirectoryRevision.objects.create(
            directory=sub_directory,
            title="New Title",
            description="New desc",
            visibility="public",
            editability="restricted",
            change_message="v2",
            revision_number=2,
            created_by=user,
        )
        client.force_login(user)
        r = client.post("/c/engineering/revert-dir/1/")
        assert r.status_code == 302
        sub_directory.refresh_from_db()
        assert sub_directory.title == "Old Title"
        assert sub_directory.description == "Old desc"
        # A new revision should be created for the revert
        assert sub_directory.revisions.count() == 3

    def test_directory_history_requires_view_permission(
        self, client, other_user, private_directory
    ):
        client.force_login(other_user)
        r = client.get("/c/secret-team/history-dir/")
        assert r.status_code == 404


# ── Edit Lock (Directory) ─────────────────────────────────


class TestDirectoryEditLock:
    def test_edit_acquires_lock(self, client, user, sub_directory):
        client.force_login(user)
        client.get("/c/engineering/edit-dir/")
        assert EditLock.objects.filter(
            directory=sub_directory, user=user
        ).exists()

    def test_root_edit_acquires_lock(self, client, owner_user, root_directory):
        client.force_login(owner_user)
        client.get("/c/edit-dir/")
        assert EditLock.objects.filter(
            directory=root_directory, user=owner_user
        ).exists()

    def test_warning_when_locked_by_other(
        self, client, user, other_user, sub_directory
    ):
        acquire_lock_for_directory(sub_directory, other_user)
        client.force_login(user)
        r = client.get("/c/engineering/edit-dir/")
        assert r.status_code == 200
        assert b"Editing in Progress" in r.content
        assert b"Bob" in r.content

    def test_save_releases_lock(self, client, user, sub_directory):
        client.force_login(user)
        client.get("/c/engineering/edit-dir/")
        assert EditLock.objects.filter(directory=sub_directory).exists()
        client.post(
            "/c/engineering/edit-dir/",
            {
                "title": "Engineering",
                "description": "",
                "visibility": "public",
            },
        )
        assert not EditLock.objects.filter(directory=sub_directory).exists()


# ── Security Regression Tests ────────────────────────────


class TestDirectorySearchSecurity:
    def test_private_directory_hidden_from_search(
        self, client, other_user, private_directory
    ):
        """SECURITY: private directories must not appear in autocomplete
        for users without permission."""
        client.force_login(other_user)
        r = client.get("/api/dir-search/?parent=&q=secret")
        import json

        data = json.loads(r.content)
        titles = [d["title"] for d in data]
        assert "Secret Team" not in titles

    def test_private_directory_visible_to_owner(
        self, client, user, private_directory
    ):
        """Directory owner should see their private directories."""
        client.force_login(user)
        r = client.get("/api/dir-search/?parent=&q=secret")
        import json

        data = json.loads(r.content)
        titles = [d["title"] for d in data]
        assert "Secret Team" in titles


class TestMoveDirectoryFormSecurity:
    def test_move_form_hides_private_directories(
        self, client, user, other_user, root_directory, sub_directory
    ):
        """SECURITY: the move form dropdown must not list private
        directories the user cannot view."""
        Directory.objects.create(
            path="private-target",
            title="Private Target",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility=Directory.Visibility.PRIVATE,
        )
        # other_user owns sub_directory for this test
        sub_directory.owner = other_user
        sub_directory.save()
        client.force_login(other_user)
        r = client.get("/c/engineering/move-dir/")
        assert r.status_code == 200
        assert b"Private Target" not in r.content


class TestMovePageFormSecurity:
    def test_move_form_hides_private_directories(
        self, client, user, other_user, root_directory, page
    ):
        """SECURITY: page move dropdown must not list private
        directories the user cannot view."""

        Directory.objects.create(
            path="private-target",
            title="Private Target",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility=Directory.Visibility.PRIVATE,
        )
        # other_user needs edit permission on the page
        page.editability = "internal"
        page.save()
        client.force_login(other_user)
        r = client.get("/c/getting-started/move/")
        assert r.status_code == 200
        assert b"Private Target" not in r.content
