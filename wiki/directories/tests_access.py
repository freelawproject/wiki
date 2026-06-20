"""Access-model view tests for the directories app."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wiki.directories.models import Directory
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
