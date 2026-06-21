"""Access-model view tests for the pages app.

Covers the #1 review fix (check_page_permissions must not leak private pages)
and the cleanup job that expires dormant domain grants.
"""

import json

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from wiki.directories.models import Directory
from wiki.pages.models import Page, PagePermission, PageRevision
from wiki.users.models import AccessTier, AllowedDomain, UserProfile


def _page(owner, slug, visibility=Page.Visibility.PUBLIC):
    p = Page.objects.create(
        title=slug,
        slug=slug,
        content="x",
        owner=owner,
        created_by=owner,
        updated_by=owner,
        visibility=visibility,
    )
    PageRevision.objects.create(
        page=p,
        title=p.title,
        content=p.content,
        change_message="init",
        revision_number=1,
        created_by=owner,
    )
    return p


class TestCheckPagePermissionsLeak:
    """#1: the mention/link advisory must not reveal private pages."""

    def test_non_editor_forbidden(self, client, user, other_user):
        # `other_user` (bob, staff) owns an internal page he can edit; alice
        # cannot edit it, so she can't use the advisory against it.
        page = _page(other_user, "secret", Page.Visibility.INTERNAL)
        # editability defaults to restricted, so alice (non-owner) can't edit.
        client.force_login(user)
        resp = client.post(
            reverse("check_page_perms"),
            data=json.dumps(
                {"page_path": page.content_path, "linked_paths": []}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_private_linked_page_not_reported(self, client, user, other_user):
        # alice owns a public page (she can edit it). It links to bob's private
        # page, which alice cannot view — it must not appear in the advisory.
        page = _page(user, "home", Page.Visibility.PUBLIC)
        secret = _page(other_user, "bobs-secret", Page.Visibility.PRIVATE)
        client.force_login(user)
        resp = client.post(
            reverse("check_page_perms"),
            data=json.dumps(
                {
                    "page_path": page.content_path,
                    "linked_paths": [secret.content_path],
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        paths = [link["path"] for link in data["restrictive_links"]]
        assert secret.content_path not in paths


class TestCleanupDormantGrants:
    def test_expires_only_stale_dormant_grants(self, db, user):
        page = _page(user, "doc")
        now = timezone.now()

        stale = PagePermission.objects.create(
            page=page,
            grant_domain="old.example",
            permission_type=PagePermission.PermissionType.VIEW,
            dormant_since=now - timezone.timedelta(days=200),
        )
        recent = PagePermission.objects.create(
            page=page,
            grant_domain="recent.example",
            permission_type=PagePermission.PermissionType.VIEW,
            dormant_since=now - timezone.timedelta(days=10),
        )
        active = PagePermission.objects.create(
            page=page,
            grant_domain="active.example",
            permission_type=PagePermission.PermissionType.VIEW,
        )

        call_command("cleanup")

        assert not PagePermission.objects.filter(pk=stale.pk).exists()
        assert PagePermission.objects.filter(pk=recent.pk).exists()
        assert PagePermission.objects.filter(pk=active.pk).exists()


@pytest.fixture
def guest(db):
    AllowedDomain.objects.create(
        domain="acme.com", suffix="acme", tier=AccessTier.GUEST
    )
    u = User.objects.create_user(
        username="carol@acme.com", email="carol@acme.com", password="x"
    )
    UserProfile.objects.create(user=u)
    return u


class TestPageMoveIsOwnerOnly:
    """A guest with an EDIT grant must not be able to move a page (which can
    change its effective visibility). Moving is owner-only."""

    def _dirs(self, owner):
        root = Directory.objects.create(path="", title="Home")
        internal = Directory.objects.create(
            path="internal",
            title="Internal",
            parent=root,
            owner=owner,
            created_by=owner,
            visibility=Directory.Visibility.INTERNAL,
        )
        public = Directory.objects.create(
            path="public",
            title="Public",
            parent=root,
            owner=owner,
            created_by=owner,
            visibility=Directory.Visibility.PUBLIC,
        )
        return internal, public

    def test_edit_grant_cannot_move_page(self, client, user, guest):
        internal, public = self._dirs(user)
        page = Page.objects.create(
            title="Secret",
            slug="secret",
            content="x",
            directory=internal,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INHERIT,
        )
        PagePermission.objects.create(
            page=page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.EDIT,
        )
        client.force_login(guest)
        client.post(
            reverse("page_move", kwargs={"path": page.content_path}),
            {"directory": public.pk},
        )
        # Denied; the page stays put (and therefore stays effectively internal).
        page.refresh_from_db()
        assert page.directory_id == internal.id

    def test_owner_can_still_move(self, client, user):
        internal, public = self._dirs(user)
        page = Page.objects.create(
            title="Doc",
            slug="doc",
            content="x",
            directory=internal,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INHERIT,
        )
        client.force_login(user)
        r = client.post(
            reverse("page_move", kwargs={"path": page.content_path}),
            {"directory": public.pk},
        )
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.directory_id == public.id

    def test_edit_grant_cannot_reparent_via_edit_form(
        self, client, user, guest
    ):
        """The page_edit location picker is a second reparenting path; a guest
        editor must not be able to use it to flip effective visibility."""
        internal, public = self._dirs(user)
        page = Page.objects.create(
            title="Secret",
            slug="secret",
            content="x",
            directory=internal,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INHERIT,
        )
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message="init",
            revision_number=1,
            created_by=user,
        )
        PagePermission.objects.create(
            page=page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.EDIT,
        )
        client.force_login(guest)
        # Guest edits content and tries to reparent to /public via the raw
        # directory_path field that the edit view reads outside the form.
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Secret",
                "content": "edited by guest",
                "change_message": "edit",
                "directory_path": "public",
            },
        )
        page.refresh_from_db()
        # Content edit is allowed; the reparent is ignored.
        assert page.directory_id == internal.id
