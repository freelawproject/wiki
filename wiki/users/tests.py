"""Tests for the users app: auth flow, magic links, permissions."""

import re

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core import mail
from django.test import Client

from wiki.users.models import SystemConfig, UserProfile


@pytest.fixture
def client():
    return Client()


class TestLoginForm:
    def test_login_page_loads(self, client, db):
        r = client.get("/u/login/")
        assert r.status_code == 200
        assert b"@free.law" in r.content

    def test_rejects_non_free_law_email(self, client, db):
        r = client.post("/u/login/", {"email": "test@gmail.com"})
        assert r.status_code == 200
        assert b"Only @free.law email addresses are allowed" in r.content

    def test_accepts_free_law_email(self, client, db):
        r = client.post("/u/login/", {"email": "test@free.law"})
        assert r.status_code == 302

    def test_email_normalized_to_lowercase(self, client, db):
        client.post("/u/login/", {"email": "TEST@FREE.LAW"})
        assert User.objects.filter(username="test@free.law").exists()


class TestMagicLinkFlow:
    def test_magic_link_email_sent(self, client, db):
        client.post("/u/login/", {"email": "alice@free.law"})
        assert len(mail.outbox) == 1
        assert "Sign in to FLP Wiki" in mail.outbox[0].subject
        assert "alice@free.law" in mail.outbox[0].to

    def test_magic_link_creates_user_and_profile(self, client, db):
        client.post("/u/login/", {"email": "new@free.law"})
        u = User.objects.get(username="new@free.law")
        assert u.email == "new@free.law"
        assert hasattr(u, "profile")
        assert u.profile.gravatar_url != ""

    def test_first_user_becomes_system_owner(self, client, db):
        client.post("/u/login/", {"email": "first@free.law"})
        config = SystemConfig.objects.get(pk=1)
        owner = User.objects.get(username="first@free.law")
        assert config.owner == owner
        assert owner.is_staff
        assert owner.is_superuser

    def test_second_user_does_not_override_owner(self, client, db):
        client.post("/u/login/", {"email": "first@free.law"})
        client.post("/u/login/", {"email": "second@free.law"})
        config = SystemConfig.objects.get(pk=1)
        assert config.owner == User.objects.get(username="first@free.law")
        second = User.objects.get(username="second@free.law")
        assert not second.is_staff
        assert not second.is_superuser

    def test_verify_with_valid_token_logs_in(self, client, db):
        client.post("/u/login/", {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        r = client.get(
            "/u/login/verify/",
            {"token": token, "email": "alice@free.law"},
        )
        assert r.status_code == 302
        assert r.url == "/c/"

    def test_verify_with_invalid_token_rejected(self, client, db):
        client.post("/u/login/", {"email": "alice@free.law"})
        r = client.get(
            "/u/login/verify/",
            {"token": "bogus", "email": "alice@free.law"},
        )
        assert r.status_code == 302
        assert r.url == "/u/login/"

    def test_verify_missing_params_rejected(self, client, db):
        r = client.get("/u/login/verify/")
        assert r.status_code == 302

    def test_token_cleared_after_use(self, client, db):
        client.post("/u/login/", {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        client.get(
            "/u/login/verify/",
            {"token": token, "email": "alice@free.law"},
        )
        profile = User.objects.get(username="alice@free.law").profile
        assert profile.magic_link_token == ""
        assert profile.magic_link_expires is None

    def test_authenticated_user_redirected_from_login(self, client, user):
        client.force_login(user)
        r = client.get("/u/login/")
        assert r.status_code == 302


class TestLogout:
    def test_logout_via_post(self, client, user):
        client.force_login(user)
        r = client.post("/u/logout/")
        assert r.status_code == 302

    def test_logout_get_does_not_logout(self, client, user):
        client.force_login(user)
        client.get("/u/logout/")
        r = client.get("/c/")
        # User should still be logged in — Sign out button shown in header
        assert b"Sign out" in r.content


class TestUserSettings:
    def test_settings_requires_login(self, client, db):
        r = client.get("/u/settings/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_settings_page_loads(self, client, user):
        client.force_login(user)
        r = client.get("/u/settings/")
        assert r.status_code == 200

    def test_update_display_name(self, client, user):
        client.force_login(user)
        r = client.post("/u/settings/", {"display_name": "Alice L."})
        assert r.status_code == 302
        user.profile.refresh_from_db()
        assert user.profile.display_name == "Alice L."


class TestUserProfileModel:
    def test_set_and_verify_token(self, user):
        profile = user.profile
        profile.set_magic_token("my-secret-token")
        profile.save()
        assert profile.verify_magic_token("my-secret-token")
        assert not profile.verify_magic_token("wrong-token")

    def test_clear_token(self, user):
        profile = user.profile
        profile.set_magic_token("my-secret-token")
        profile.save()
        profile.clear_magic_token()
        profile.save()
        assert not profile.verify_magic_token("my-secret-token")

    def test_gravatar_url_deterministic(self):
        url1 = UserProfile.gravatar_url_for_email("Test@Example.COM")
        url2 = UserProfile.gravatar_url_for_email("test@example.com")
        assert url1 == url2


class TestAdminList:
    """Part 6: Admin promotion UI."""

    def test_admin_list_requires_staff(self, client, user):
        client.force_login(user)
        r = client.get("/u/admins/")
        assert r.status_code == 404

    def test_admin_list_visible_to_staff(self, client, user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get("/u/admins/")
        assert r.status_code == 200

    def test_admin_list_visible_to_system_owner(self, client, owner_user):
        client.force_login(owner_user)
        r = client.get("/u/admins/")
        assert r.status_code == 200

    def test_admin_list_shows_users(self, client, user, other_user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get("/u/admins/")
        content = r.content.decode()
        assert "alice@free.law" in content
        assert "bob@free.law" in content

    def test_promote_user_to_admin(self, client, user, other_user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(f"/u/admins/{other_user.pk}/toggle/")
        assert r.status_code == 302
        other_user.refresh_from_db()
        assert other_user.is_staff is True
        assert other_user.is_superuser is True

    def test_demote_admin(self, client, user, other_user):
        user.is_staff = True
        user.save()
        other_user.is_staff = True
        other_user.is_superuser = True
        other_user.save()
        client.force_login(user)
        r = client.post(f"/u/admins/{other_user.pk}/toggle/")
        assert r.status_code == 302
        other_user.refresh_from_db()
        assert other_user.is_staff is False
        assert other_user.is_superuser is False

    def test_cannot_demote_system_owner(self, client, owner_user, other_user):
        owner_user.is_staff = True
        owner_user.save()
        other_user.is_staff = True
        other_user.save()
        client.force_login(other_user)
        r = client.post(f"/u/admins/{owner_user.pk}/toggle/")
        assert r.status_code == 302
        owner_user.refresh_from_db()
        assert owner_user.is_staff is True  # Not demoted

    def test_non_staff_cannot_toggle(self, client, user, other_user):
        client.force_login(user)
        r = client.post(f"/u/admins/{other_user.pk}/toggle/")
        assert r.status_code == 404

    def test_header_admin_link_for_staff(self, client, user, root_directory):
        """Staff users see Admin link in header."""
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get("/c/")
        assert b"/u/admins/" in r.content

    def test_header_no_admin_link_for_regular_user(
        self, client, user, root_directory
    ):
        """Regular users don't see Admin link."""
        client.force_login(user)
        r = client.get("/c/")
        assert b"/u/admins/" not in r.content


class TestUserArchiving:
    """User archiving: deactivate account, delete sessions, block login."""

    def test_archived_user_cannot_request_magic_link(self, client, user):
        """Archived user submits login form — gets error, no email."""
        user.is_active = False
        user.save(update_fields=["is_active"])
        r = client.post("/u/login/", {"email": "alice@free.law"}, follow=True)
        assert b"archived" in r.content.lower()
        assert len(mail.outbox) == 0

    def test_archived_user_cannot_verify_magic_link(self, client, user):
        """Archived user with valid token is rejected at verify."""
        # Generate a valid token first
        client.post("/u/login/", {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        # Now archive the user
        user.is_active = False
        user.save(update_fields=["is_active"])
        r = client.get(
            "/u/login/verify/",
            {"token": token, "email": "alice@free.law"},
            follow=True,
        )
        assert b"archived" in r.content.lower()

    def test_admin_can_archive_user(self, client, user, other_user):
        """POST to archive toggle sets is_active=False."""
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(f"/u/admins/{other_user.pk}/archive/")
        assert r.status_code == 302
        other_user.refresh_from_db()
        assert other_user.is_active is False

    def test_admin_can_unarchive_user(self, client, user, other_user):
        """POST to unarchive toggle sets is_active=True."""
        user.is_staff = True
        user.save()
        other_user.is_active = False
        other_user.save(update_fields=["is_active"])
        client.force_login(user)
        r = client.post(f"/u/admins/{other_user.pk}/archive/")
        assert r.status_code == 302
        other_user.refresh_from_db()
        assert other_user.is_active is True

    def test_cannot_archive_system_owner(self, client, owner_user, other_user):
        """Archive toggle rejects system owner."""
        other_user.is_staff = True
        other_user.save()
        client.force_login(other_user)
        r = client.post(f"/u/admins/{owner_user.pk}/archive/", follow=True)
        assert b"Cannot archive the system owner" in r.content
        owner_user.refresh_from_db()
        assert owner_user.is_active is True

    def test_archiving_deletes_user_sessions(self, client, user, other_user):
        """Archiving a user deletes their sessions from DB."""
        # Log in other_user to create a session
        other_client = Client()
        other_client.force_login(other_user)
        # Make a request to ensure session is persisted
        other_client.get("/c/", follow=True)

        # Verify session exists
        sessions_before = []
        for s in Session.objects.all():
            if s.get_decoded().get(SESSION_KEY) == str(other_user.pk):
                sessions_before.append(s.session_key)
        assert len(sessions_before) > 0

        # Archive other_user
        user.is_staff = True
        user.save()
        client.force_login(user)
        client.post(f"/u/admins/{other_user.pk}/archive/")

        # Verify sessions are deleted
        sessions_after = []
        for s in Session.objects.all():
            if s.get_decoded().get(SESSION_KEY) == str(other_user.pk):
                sessions_after.append(s.session_key)
        assert len(sessions_after) == 0

    def test_admin_list_shows_archived_badge(self, client, user, other_user):
        """Archived users show 'Archived' badge in admin list."""
        user.is_staff = True
        user.save()
        other_user.is_active = False
        other_user.save(update_fields=["is_active"])
        client.force_login(user)
        r = client.get("/u/admins/")
        assert b"Archived" in r.content
