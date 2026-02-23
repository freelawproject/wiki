"""Tests for the groups app: list, create, edit, delete, members."""

import pytest
from django.contrib.auth.models import Group
from django.test import Client


@pytest.fixture
def client():
    return Client()


class TestGroupList:
    def test_list_requires_login(self, client, db):
        r = client.get("/u/admins/groups/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_list_shows_groups(self, client, user, group):
        client.force_login(user)
        r = client.get("/u/admins/groups/")
        assert r.status_code == 200
        assert b"Engineering Team" in r.content

    def test_list_shows_member_count(self, client, user, group):
        user.groups.add(group)
        client.force_login(user)
        r = client.get("/u/admins/groups/")
        assert b"1 member" in r.content


class TestGroupCreate:
    def test_create_requires_staff(self, client, user, db):
        client.force_login(user)
        r = client.get("/u/admins/groups/new/")
        # Non-staff redirected with error
        assert r.status_code == 302

    def test_staff_can_create(self, client, user, db):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post("/u/admins/groups/new/", {"name": "Backend"})
        assert r.status_code == 302
        assert Group.objects.filter(name="Backend").exists()

    def test_system_owner_can_create(self, client, owner_user, db):
        client.force_login(owner_user)
        r = client.post("/u/admins/groups/new/", {"name": "Frontend"})
        assert r.status_code == 302
        assert Group.objects.filter(name="Frontend").exists()

    def test_duplicate_name_rejected(self, client, user, group):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post("/u/admins/groups/new/", {"name": "Engineering Team"})
        # Stays on form with error
        assert r.status_code == 200


class TestGroupDetail:
    def test_detail_shows_members(self, client, user, other_user, group):
        other_user.groups.add(group)
        client.force_login(user)
        r = client.get(f"/u/admins/groups/{group.pk}/")
        assert r.status_code == 200
        assert b"Bob" in r.content

    def test_add_member(self, client, user, other_user, group):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(
            f"/u/admins/groups/{group.pk}/add-member/",
            {"username": "bob"},
        )
        assert r.status_code == 302
        assert group.user_set.filter(pk=other_user.pk).exists()

    def test_add_nonexistent_user(self, client, user, group):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(
            f"/u/admins/groups/{group.pk}/add-member/",
            {"username": "nobody"},
        )
        assert r.status_code == 302
        assert group.user_set.count() == 0

    def test_remove_member(self, client, user, other_user, group):
        user.is_staff = True
        user.save()
        other_user.groups.add(group)
        client.force_login(user)
        r = client.post(
            f"/u/admins/groups/{group.pk}/remove-member/",
            {"user_id": other_user.pk},
        )
        assert r.status_code == 302
        assert not group.user_set.filter(pk=other_user.pk).exists()

    def test_non_staff_cannot_add_member(
        self, client, user, other_user, group
    ):
        client.force_login(user)
        client.post(
            f"/u/admins/groups/{group.pk}/add-member/",
            {"username": "bob"},
        )
        assert not group.user_set.filter(pk=other_user.pk).exists()


class TestGroupEdit:
    def test_edit_group_name(self, client, user, group):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(
            f"/u/admins/groups/{group.pk}/edit/", {"name": "Eng Team"}
        )
        assert r.status_code == 302
        group.refresh_from_db()
        assert group.name == "Eng Team"

    def test_non_staff_cannot_edit(self, client, user, group):
        client.force_login(user)
        r = client.post(
            f"/u/admins/groups/{group.pk}/edit/", {"name": "Hacked"}
        )
        assert r.status_code == 302
        group.refresh_from_db()
        assert group.name == "Engineering Team"


class TestGroupDelete:
    def test_delete_requires_staff(self, client, user, group):
        client.force_login(user)
        r = client.post(f"/u/admins/groups/{group.pk}/delete/")
        assert r.status_code == 302
        assert Group.objects.filter(pk=group.pk).exists()

    def test_staff_can_delete(self, client, user, group):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(f"/u/admins/groups/{group.pk}/delete/")
        assert r.status_code == 302
        assert not Group.objects.filter(pk=group.pk).exists()


class TestOldGroupUrlsRemoved:
    def test_old_group_urls_gone(self, client, user, group):
        """The /g/ URLs should no longer be routed."""
        client.force_login(user)
        r = client.get("/g/")
        assert r.status_code == 404


class TestGroupEmailSecurity:
    def test_group_detail_does_not_expose_emails(
        self, client, user, other_user, group
    ):
        """SECURITY: group detail page must not show full email addresses."""
        other_user.groups.add(group)
        client.force_login(user)
        r = client.get(f"/u/admins/groups/{group.pk}/")
        assert r.status_code == 200
        # Display name should appear, but full email must not
        assert b"Bob" in r.content
        assert b"bob@free.law" not in r.content
