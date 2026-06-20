"""Access-model view tests for the directories app."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wiki.directories.models import Directory, DirectoryPermission
from wiki.pages.models import Page, PagePermission, PageRevision
from wiki.users.models import AccessTier, AllowedDomain, UserProfile


@pytest.fixture
def carol(db):
    AllowedDomain.objects.create(
        domain="acme.com", suffix="acme", tier=AccessTier.GUEST
    )
    u = User.objects.create_user(
        username="carol@acme.com", email="carol@acme.com", password="x"
    )
    UserProfile.objects.create(user=u)
    return u


@pytest.fixture
def private_dir(user):
    root = Directory.objects.create(path="", title="Home")
    return Directory.objects.create(
        path="secret",
        title="Secret",
        parent=root,
        owner=user,
        created_by=user,
        visibility=Directory.Visibility.PRIVATE,
    )


class TestInheritMetaGate:
    """directory_inherit_meta must not reveal directories you can't view."""

    def test_non_viewer_gets_404(self, client, carol, private_dir):
        client.force_login(carol)
        resp = client.get(
            reverse("dir_inherit_meta"), {"path": private_dir.path}
        )
        assert resp.status_code == 404

    def test_owner_gets_metadata(self, client, user, private_dir):
        client.force_login(user)
        resp = client.get(
            reverse("dir_inherit_meta"), {"path": private_dir.path}
        )
        assert resp.status_code == 200
        assert "visibility" in resp.json()

    def test_missing_directory_also_404(self, client, user):
        client.force_login(user)
        resp = client.get(reverse("dir_inherit_meta"), {"path": "nope/nope"})
        assert resp.status_code == 404


class TestApplyPermissionsCopiesDomainGrants:
    """Applying a directory's permissions to its children must copy domain
    grants (the third subject type), not silently drop them or 500."""

    def test_domain_grant_applied_to_child_page(self, client, user):
        root = Directory.objects.create(path="", title="Home")
        parent = Directory.objects.create(
            path="team",
            title="Team",
            parent=root,
            owner=user,
            created_by=user,
        )
        page = Page.objects.create(
            title="Doc",
            slug="doc",
            content="x",
            directory=parent,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message="init",
            revision_number=1,
            created_by=user,
        )
        # A pre-existing user grant of the same type on the child is the case
        # that used to make get_or_create match/clobber or raise.
        PagePermission.objects.create(
            page=page,
            user=user,
            permission_type=PagePermission.PermissionType.VIEW,
        )
        # Domain grant on the parent directory.
        DirectoryPermission.objects.create(
            directory=parent,
            grant_domain="acme.com",
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )

        client.force_login(user)
        r = client.post(
            reverse(
                "directory_apply_permissions", kwargs={"path": parent.path}
            ),
            {"scope": "direct"},
        )
        assert r.status_code == 302
        # The domain grant was copied onto the child page (not lost), and the
        # pre-existing user grant is still intact.
        assert PagePermission.objects.filter(
            page=page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        ).exists()
        assert PagePermission.objects.filter(
            page=page,
            user=user,
            permission_type=PagePermission.PermissionType.VIEW,
        ).exists()
