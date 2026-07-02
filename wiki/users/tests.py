"""Tests for the users app: auth flow, magic links, permissions."""

import re

import pytest
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory
from django.urls import reverse

from wiki.lib.access import is_email_allowed
from wiki.lib.users import user_by_handle
from wiki.lib.views import ratelimited
from wiki.users.models import (
    AllowedDomain,
    AllowedEmail,
    SystemConfig,
    UserProfile,
)


@pytest.fixture
def client():
    return Client()


class TestLoginForm:
    def test_login_page_loads(self, client, db):
        r = client.get(reverse("login"))
        assert r.status_code == 200
        assert b"Send Sign-In Link" in r.content

    def test_disallowed_email_gets_neutral_response(self, client, db):
        # SECURITY: the response must be identical to an allowed address so
        # the form can't be used to enumerate the allowlist — a neutral
        # redirect, no account created, no email sent.
        r = client.post(reverse("login"), {"email": "test@gmail.com"})
        assert r.status_code == 302
        assert not User.objects.filter(username="test@gmail.com").exists()
        assert len(mail.outbox) == 0

    def test_accepts_seeded_free_law_domain(self, client, db):
        # The data migration seeds free.law as an allowed domain.
        r = client.post(reverse("login"), {"email": "test@free.law"})
        assert r.status_code == 302

    def test_accepts_other_allowed_domain(self, client, db):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        r = client.post(reverse("login"), {"email": "person@example.org"})
        assert r.status_code == 302
        assert User.objects.filter(username="person@example.org").exists()

    def test_accepts_individual_allowed_email(self, client, db):
        AllowedEmail.objects.create(email="contractor@gmail.com")
        r = client.post(reverse("login"), {"email": "contractor@gmail.com"})
        assert r.status_code == 302
        assert User.objects.filter(username="contractor@gmail.com").exists()
        # A different address on the same (non-allowed) domain is not minted,
        # though the response looks identical (neutral redirect).
        r2 = client.post(reverse("login"), {"email": "someone@gmail.com"})
        assert r2.status_code == 302
        assert not User.objects.filter(username="someone@gmail.com").exists()

    def test_email_normalized_to_lowercase(self, client, db):
        client.post(reverse("login"), {"email": "TEST@FREE.LAW"})
        assert User.objects.filter(username="test@free.law").exists()

    def test_rejects_plus_addressing(self, client, db):
        r = client.post(reverse("login"), {"email": "mike+foo@free.law"})
        assert r.status_code == 302
        assert not User.objects.filter(username="mike+foo@free.law").exists()
        assert len(mail.outbox) == 0


class TestMagicLinkFlow:
    def test_magic_link_email_sent(self, client, db):
        client.post(reverse("login"), {"email": "alice@free.law"})
        assert len(mail.outbox) == 1
        assert "Sign in to FLP Wiki" in mail.outbox[0].subject
        assert "alice@free.law" in mail.outbox[0].to

    def test_magic_link_creates_user_and_profile(self, client, db):
        client.post(reverse("login"), {"email": "new@free.law"})
        u = User.objects.get(username="new@free.law")
        assert u.email == "new@free.law"
        assert hasattr(u, "profile")
        assert u.profile.gravatar_url != ""

    def test_first_user_becomes_system_owner(self, client, db):
        client.post(reverse("login"), {"email": "first@free.law"})
        config = SystemConfig.objects.get(pk=1)
        owner = User.objects.get(username="first@free.law")
        assert config.owner == owner
        assert owner.is_staff
        assert owner.is_superuser

    def test_second_user_does_not_override_owner(self, client, db):
        client.post(reverse("login"), {"email": "first@free.law"})
        client.post(reverse("login"), {"email": "second@free.law"})
        config = SystemConfig.objects.get(pk=1)
        assert config.owner == User.objects.get(username="first@free.law")
        second = User.objects.get(username="second@free.law")
        assert not second.is_staff
        assert not second.is_superuser

    def test_verify_with_valid_token_logs_in(self, client, db):
        client.post(reverse("login"), {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        r = client.get(
            reverse("verify"),
            {"token": token, "email": "alice@free.law"},
        )
        assert r.status_code == 302
        assert r.url == reverse("root")

    def test_verify_with_invalid_token_rejected(self, client, db):
        client.post(reverse("login"), {"email": "alice@free.law"})
        r = client.get(
            reverse("verify"),
            {"token": "bogus", "email": "alice@free.law"},
        )
        assert r.status_code == 302
        assert r.url == reverse("login")

    def test_verify_missing_params_rejected(self, client, db):
        r = client.get(reverse("verify"))
        assert r.status_code == 302

    def test_token_cleared_after_use(self, client, db):
        client.post(reverse("login"), {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        client.get(
            reverse("verify"),
            {"token": token, "email": "alice@free.law"},
        )
        profile = User.objects.get(username="alice@free.law").profile
        assert profile.magic_link_token == ""
        assert profile.magic_link_expires is None

    def test_authenticated_user_redirected_from_login(self, client, user):
        client.force_login(user)
        r = client.get(reverse("login"))
        assert r.status_code == 302


class TestNextRedirect:
    """The ?next= target must survive the whole magic link round trip."""

    def _magic_link_query(self):
        """Parse the verify URL's query string out of the sent email."""
        m = re.search(r"\?(\S+)", mail.outbox[0].body)
        return m.group(1)

    def test_login_page_renders_hidden_next_field(self, client, db):
        r = client.get(reverse("login"), {"next": "/c/some-page/"})
        assert b'name="next" value="/c/some-page/"' in r.content

    def test_login_page_drops_offsite_next(self, client, db):
        # SECURITY: an off-host next must not propagate (open redirect).
        r = client.get(reverse("login"), {"next": "https://evil.example.com/"})
        assert b'name="next"' not in r.content

    def test_next_carried_into_magic_link(self, client, db):
        client.post(
            reverse("login"),
            {"email": "alice@free.law", "next": "/c/some-page/"},
        )
        assert "next=%2Fc%2Fsome-page%2F" in self._magic_link_query()

    def test_offsite_next_dropped_from_magic_link(self, client, db):
        client.post(
            reverse("login"),
            {"email": "alice@free.law", "next": "https://evil.example.com/"},
        )
        assert "next=" not in self._magic_link_query()

    def test_post_redirect_preserves_next(self, client, db):
        r = client.post(
            reverse("login"),
            {"email": "alice@free.law", "next": "/c/some-page/"},
        )
        assert r.url == reverse("login") + "?next=%2Fc%2Fsome-page%2F"

    def test_verify_redirects_to_next(self, client, db):
        client.post(
            reverse("login"),
            {"email": "alice@free.law", "next": "/c/some-page/"},
        )
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        r = client.get(
            reverse("verify"),
            {
                "token": token,
                "email": "alice@free.law",
                "next": "/c/some-page/",
            },
        )
        assert r.status_code == 302
        assert r.url == "/c/some-page/"

    def test_verify_ignores_bare_pattern_name_next(self, client, db):
        # SECURITY: a schemeless, hostless string like "admin_list" passes
        # url_has_allowed_host_and_scheme but redirect() would reverse() it
        # as a URL pattern name (or 500 on NoReverseMatch). Only real paths
        # (leading slash) may pass through.
        client.post(reverse("login"), {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        r = client.get(
            reverse("verify"),
            {
                "token": token,
                "email": "alice@free.law",
                "next": "admin_list",
            },
        )
        assert r.status_code == 302
        assert r.url == reverse("root")

    def test_verify_ignores_offsite_next(self, client, db):
        # SECURITY: the verify link is attacker-composable, so an off-host
        # next must fall back to root instead of redirecting away.
        client.post(reverse("login"), {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        r = client.get(
            reverse("verify"),
            {
                "token": token,
                "email": "alice@free.law",
                "next": "https://evil.example.com/",
            },
        )
        assert r.status_code == 302
        assert r.url == reverse("root")

    def test_authenticated_user_follows_next_from_login(self, client, user):
        client.force_login(user)
        r = client.get(reverse("login"), {"next": "/c/some-page/"})
        assert r.status_code == 302
        assert r.url == "/c/some-page/"

    def test_login_required_page_links_next_through_form(self, client, db):
        # End to end: a protected page bounces to login?next=..., and that
        # value must come back out of the rendered form.
        settings_url = reverse("user_settings")
        r = client.get(settings_url)
        assert r.status_code == 302
        login_url = r.url
        assert "?next=" in login_url
        r = client.get(login_url)
        expected = f'name="next" value="{settings_url}"'
        assert expected.encode() in r.content


class TestLogout:
    def test_logout_via_post(self, client, user):
        client.force_login(user)
        r = client.post(reverse("logout"))
        assert r.status_code == 302

    def test_logout_get_does_not_logout(self, client, user):
        client.force_login(user)
        client.get(reverse("logout"))
        r = client.get(reverse("root"))
        # User should still be logged in — Sign out button shown in header
        assert b"Sign out" in r.content


class TestUserSettings:
    def test_settings_requires_login(self, client, db):
        r = client.get(reverse("user_settings"))
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_settings_page_loads(self, client, user):
        client.force_login(user)
        r = client.get(reverse("user_settings"))
        assert r.status_code == 200

    def test_update_display_name(self, client, user):
        client.force_login(user)
        r = client.post(reverse("user_settings"), {"display_name": "Alice L."})
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
        r = client.get(reverse("admin_list"))
        assert r.status_code == 404

    def test_admin_list_visible_to_staff(self, client, user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get(reverse("admin_list"))
        assert r.status_code == 200

    def test_admin_list_visible_to_system_owner(self, client, owner_user):
        client.force_login(owner_user)
        r = client.get(reverse("admin_list"))
        assert r.status_code == 200

    def test_admin_list_shows_users(self, client, user, other_user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get(reverse("admin_list"))
        content = r.content.decode()
        assert "alice@free.law" in content
        assert "bob@free.law" in content

    def test_promote_user_to_admin(self, client, user, other_user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(reverse("admin_toggle", kwargs={"pk": other_user.pk}))
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
        r = client.post(reverse("admin_toggle", kwargs={"pk": other_user.pk}))
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
        r = client.post(reverse("admin_toggle", kwargs={"pk": owner_user.pk}))
        assert r.status_code == 302
        owner_user.refresh_from_db()
        assert owner_user.is_staff is True  # Not demoted

    def test_non_staff_cannot_toggle(self, client, user, other_user):
        client.force_login(user)
        r = client.post(reverse("admin_toggle", kwargs={"pk": other_user.pk}))
        assert r.status_code == 404

    def test_header_admin_link_for_staff(self, client, user, root_directory):
        """Staff users see Admin link in header."""
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get(reverse("root"))
        assert reverse("admin_list").encode() in r.content

    def test_header_no_admin_link_for_regular_user(
        self, client, user, root_directory
    ):
        """Regular users don't see Admin link."""
        client.force_login(user)
        r = client.get(reverse("root"))
        assert reverse("admin_list").encode() not in r.content


class TestUserArchiving:
    """User archiving: deactivate account, delete sessions, block login."""

    def test_archived_user_cannot_request_magic_link(self, client, user):
        """Archived user submits login form — no email, neutral response.

        The response no longer reveals the archive state (that would leak who
        has an account); the security property is that no link is sent.
        """
        user.is_active = False
        user.save(update_fields=["is_active"])
        r = client.post(
            reverse("login"), {"email": "alice@free.law"}, follow=True
        )
        assert len(mail.outbox) == 0
        assert b"allowed to sign in" in r.content.lower()

    def test_archived_user_cannot_verify_magic_link(self, client, user):
        """Archived user with valid token is rejected at verify."""
        # Generate a valid token first
        client.post(reverse("login"), {"email": "alice@free.law"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)
        # Now archive the user
        user.is_active = False
        user.save(update_fields=["is_active"])
        r = client.get(
            reverse("verify"),
            {"token": token, "email": "alice@free.law"},
            follow=True,
        )
        assert b"archived" in r.content.lower()

    def test_admin_can_archive_user(self, client, user, other_user):
        """POST to archive toggle sets is_active=False."""
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(
            reverse("admin_archive_toggle", kwargs={"pk": other_user.pk})
        )
        assert r.status_code == 302
        other_user.refresh_from_db()
        assert other_user.is_active is False

    def test_archiving_clears_outstanding_magic_link(
        self, client, user, other_user
    ):
        """Archiving kills the user's outstanding magic-link token."""
        user.is_staff = True
        user.save()
        other_user.profile.set_magic_token("a-token")
        other_user.profile.save()
        client.force_login(user)
        client.post(
            reverse("admin_archive_toggle", kwargs={"pk": other_user.pk})
        )
        other_user.profile.refresh_from_db()
        assert other_user.profile.magic_link_token == ""
        assert other_user.profile.magic_link_expires is None

    def test_admin_can_unarchive_user(self, client, user, other_user):
        """POST to unarchive toggle sets is_active=True."""
        user.is_staff = True
        user.save()
        other_user.is_active = False
        other_user.save(update_fields=["is_active"])
        client.force_login(user)
        r = client.post(
            reverse("admin_archive_toggle", kwargs={"pk": other_user.pk})
        )
        assert r.status_code == 302
        other_user.refresh_from_db()
        assert other_user.is_active is True

    def test_cannot_archive_system_owner(self, client, owner_user, other_user):
        """Archive toggle rejects system owner."""
        other_user.is_staff = True
        other_user.save()
        client.force_login(other_user)
        r = client.post(
            reverse("admin_archive_toggle", kwargs={"pk": owner_user.pk}),
            follow=True,
        )
        assert b"Cannot archive the system owner" in r.content
        owner_user.refresh_from_db()
        assert owner_user.is_active is True

    def test_archiving_deletes_user_sessions(self, client, user, other_user):
        """Archiving a user deletes their sessions from DB."""
        # Log in other_user to create a session
        other_client = Client()
        other_client.force_login(other_user)
        # Make a request to ensure session is persisted
        other_client.get(reverse("root"), follow=True)

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
        client.post(
            reverse("admin_archive_toggle", kwargs={"pk": other_user.pk})
        )

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
        r = client.get(reverse("admin_list"))
        assert b"Archived" in r.content


class TestAdminEmailDomainSecurity:
    def test_django_admin_rejects_non_free_law_email(self, client, user):
        """SECURITY: the Django admin must not allow creating users with
        non-@free.law email addresses."""
        user.is_staff = True
        user.is_superuser = True
        user.save()
        client.force_login(user)
        client.post(
            reverse("admin:auth_user_add"),
            {
                "username": "hacker@gmail.com",
                "email": "hacker@gmail.com",
                "password1": "Str0ngP@ss!",
                "password2": "Str0ngP@ss!",
            },
        )
        # The user should NOT be created
        assert not User.objects.filter(email="hacker@gmail.com").exists()

    def test_django_admin_rejects_blank_email(self, client, user):
        """SECURITY: a blank email must not skip the allowlist check."""
        user.is_staff = True
        user.is_superuser = True
        user.save()
        client.force_login(user)
        client.post(
            reverse("admin:auth_user_add"),
            {
                "username": "svc-account",
                "email": "",
                "password1": "Str0ngP@ss!",
                "password2": "Str0ngP@ss!",
            },
        )
        assert not User.objects.filter(username="svc-account").exists()


class TestAccessAllowlist:
    """Sign-in allowlist model + admin management UI."""

    def test_is_email_allowed_helper(self, db):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        AllowedEmail.objects.create(email="solo@gmail.com")
        assert is_email_allowed("anyone@example.org")
        assert is_email_allowed("ANYONE@EXAMPLE.ORG")
        assert is_email_allowed("solo@gmail.com")
        assert not is_email_allowed("other@gmail.com")
        assert not is_email_allowed("not-an-email")

    def test_is_email_allowed_rejects_bypass_shapes(self, db):
        AllowedDomain.objects.get_or_create(domain="free.law")
        # The domain after the last "@" is free.law in all of these, but
        # they must not be treated as a valid allowed address.
        assert not is_email_allowed("evil@evil.com@free.law")  # multiple @
        assert not is_email_allowed('"evil@evil.com"@free.law')  # quoted @
        assert not is_email_allowed("@free.law")  # empty local part
        assert not is_email_allowed("user@free.law.")  # trailing dot
        assert not is_email_allowed("user@")  # empty domain
        assert not is_email_allowed(None)

    def test_is_email_allowed_rejects_plus_addressing(self, db):
        # mike+foo@free.law delivers to mike@free.law; blocking it stops one
        # mailbox minting many accounts / evading per-account archiving.
        AllowedDomain.objects.get_or_create(domain="free.law")
        assert not is_email_allowed("mike+foo@free.law")
        assert is_email_allowed("mike@free.law")  # base address still works

    def test_domain_normalized_on_save(self, db):
        d = AllowedDomain.objects.create(
            domain="  @Example.ORG. ".strip(), suffix="ex"
        )
        d.refresh_from_db()
        assert d.domain == "example.org"

    def test_access_list_requires_staff(self, client, user):
        client.force_login(user)
        r = client.get(reverse("access_list"))
        assert r.status_code == 404

    def test_access_list_visible_to_staff(self, client, user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.get(reverse("access_list"))
        assert r.status_code == 200
        assert b"free.law" in r.content

    def test_owner_can_add_domain(self, client, owner_user):
        client.force_login(owner_user)
        r = client.post(
            reverse("access_add_domain"),
            {"domain": "Example.ORG", "suffix": "ex", "note": "Partner org"},
        )
        assert r.status_code == 302
        d = AllowedDomain.objects.get(domain="example.org")
        assert d.suffix == "ex"

    def test_add_invalid_domain_rejected(self, client, owner_user):
        client.force_login(owner_user)
        client.post(
            reverse("access_add_domain"),
            {"domain": "not a domain", "suffix": "x"},
        )
        assert not AllowedDomain.objects.filter(domain="not a domain").exists()

    def test_staff_can_add_email(self, client, user):
        user.is_staff = True
        user.save()
        client.force_login(user)
        r = client.post(
            reverse("access_add_email"),
            {"email": "Contractor@Gmail.com"},
        )
        assert r.status_code == 302
        assert AllowedEmail.objects.filter(
            email="contractor@gmail.com"
        ).exists()

    def test_owner_can_remove_domain(self, client, owner_user):
        client.force_login(owner_user)
        d = AllowedDomain.objects.create(domain="example.org", suffix="ex")
        r = client.post(reverse("access_delete_domain", kwargs={"pk": d.pk}))
        assert r.status_code == 302
        assert not AllowedDomain.objects.filter(pk=d.pk).exists()

    def test_non_staff_cannot_add_domain(self, client, user):
        client.force_login(user)
        r = client.post(reverse("access_add_domain"), {"domain": "evil.com"})
        assert r.status_code == 404
        assert not AllowedDomain.objects.filter(domain="evil.com").exists()


class TestAccessChangePermissionsAndEmails:
    """Domains are owner-only; emails are owner/manager. Every change
    notifies the owner and managers and confirms to the actor on-site."""

    def _make_manager(self, mgr):
        mgr.is_staff = True
        mgr.save()
        return mgr

    def test_manager_cannot_add_domain(self, client, owner_user, other_user):
        # other_user is a manager (staff) but not the owner.
        self._make_manager(other_user)
        client.force_login(other_user)
        r = client.post(
            reverse("access_add_domain"),
            {"domain": "example.org"},
            follow=True,
        )
        assert not AllowedDomain.objects.filter(domain="example.org").exists()
        assert b"Only the system owner" in r.content
        assert len(mail.outbox) == 0

    def test_manager_cannot_delete_domain(
        self, client, owner_user, other_user
    ):
        self._make_manager(other_user)
        d = AllowedDomain.objects.create(domain="example.org", suffix="ex")
        client.force_login(other_user)
        client.post(reverse("access_delete_domain", kwargs={"pk": d.pk}))
        assert AllowedDomain.objects.filter(pk=d.pk).exists()
        assert len(mail.outbox) == 0

    def test_owner_add_domain_notifies_owner_and_managers(
        self, client, owner_user, other_user
    ):
        self._make_manager(other_user)
        client.force_login(owner_user)
        r = client.post(
            reverse("access_add_domain"),
            {"domain": "example.org", "suffix": "ex"},
            follow=True,
        )
        assert AllowedDomain.objects.filter(domain="example.org").exists()
        assert len(mail.outbox) == 1
        recipients = set(mail.outbox[0].to)
        assert "alice@free.law" in recipients  # owner
        assert "bob@free.law" in recipients  # manager
        assert b"notified by email" in r.content

    def test_owner_delete_domain_notifies(self, client, owner_user):
        d = AllowedDomain.objects.create(domain="example.org", suffix="ex")
        client.force_login(owner_user)
        client.post(reverse("access_delete_domain", kwargs={"pk": d.pk}))
        assert not AllowedDomain.objects.filter(pk=d.pk).exists()
        assert len(mail.outbox) == 1

    def test_manager_add_email_notifies_owner_and_managers(
        self, client, owner_user, other_user
    ):
        self._make_manager(other_user)
        client.force_login(other_user)  # manager, not owner
        r = client.post(
            reverse("access_add_email"),
            {"email": "contractor@gmail.com"},
            follow=True,
        )
        assert AllowedEmail.objects.filter(
            email="contractor@gmail.com"
        ).exists()
        # Two emails: one to the new grantee, one to the owner + managers.
        assert len(mail.outbox) == 2
        grantee = [m for m in mail.outbox if m.to == ["contractor@gmail.com"]]
        audit = [m for m in mail.outbox if "alice@free.law" in m.to]
        assert len(grantee) == 1
        assert len(audit) == 1
        assert "bob@free.law" in set(audit[0].to)  # manager (actor)
        assert b"notified by email" in r.content

    def test_manager_delete_email_notifies(
        self, client, owner_user, other_user
    ):
        self._make_manager(other_user)
        e = AllowedEmail.objects.create(email="contractor@gmail.com")
        client.force_login(other_user)
        client.post(reverse("access_delete_email", kwargs={"pk": e.pk}))
        assert not AllowedEmail.objects.filter(pk=e.pk).exists()
        assert len(mail.outbox) == 1

    def test_no_duplicate_add_no_email(self, client, owner_user):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        client.force_login(owner_user)
        # A distinct suffix passes validation; the duplicate domain is the
        # no-op path that must not email anyone.
        client.post(
            reverse("access_add_domain"),
            {"domain": "example.org", "suffix": "ex2"},
        )
        assert len(mail.outbox) == 0


def _make_user(email):
    """Create a User + profile (so the post_save signal assigns a handle)."""
    u = User.objects.create_user(username=email, email=email)
    UserProfile.objects.create(user=u)
    return u


def _has_active_session(user):
    return any(
        s.get_decoded().get(SESSION_KEY) == str(user.pk)
        for s in Session.objects.all()
    )


class TestHandleAssignment:
    """Handles are unique; collisions use the domain suffix, else a number."""

    def test_first_claimant_gets_bare_handle(self, user):
        # The `user` fixture is alice@free.law.
        assert user.profile.handle == "alice"

    def test_collision_uses_domain_suffix(self, db):
        AllowedDomain.objects.create(domain="wrrrk.com", suffix="wrrrk")
        first = _make_user("mike@free.law")
        second = _make_user("mike@wrrrk.com")
        assert first.profile.handle == "mike"
        assert second.profile.handle == "mike-wrrrk"

    def test_allowed_email_collision_uses_number(self, db):
        # contractor domain isn't an AllowedDomain, so there's no suffix.
        AllowedEmail.objects.create(email="mike@contractor.io")
        first = _make_user("mike@free.law")
        second = _make_user("mike@contractor.io")
        assert first.profile.handle == "mike"
        assert second.profile.handle == "mike-2"


class TestUserByHandle:
    def test_resolves_by_handle(self, user):
        assert user_by_handle("alice") == user

    def test_handle_lookup_is_case_insensitive(self, user):
        assert user_by_handle("ALICE") == user

    def test_unknown_handle_returns_none(self, db):
        assert user_by_handle("nobody") is None

    def test_blank_returns_none(self, db):
        assert user_by_handle("") is None


class TestDomainSuffixForm:
    def test_suffix_required(self, client, owner_user):
        client.force_login(owner_user)
        client.post(reverse("access_add_domain"), {"domain": "example.org"})
        assert not AllowedDomain.objects.filter(domain="example.org").exists()

    def test_duplicate_suffix_rejected(self, client, owner_user):
        AllowedDomain.objects.create(domain="a.com", suffix="acme")
        client.force_login(owner_user)
        client.post(
            reverse("access_add_domain"),
            {"domain": "b.com", "suffix": "acme"},
        )
        assert not AllowedDomain.objects.filter(domain="b.com").exists()

    def test_non_slug_suffix_rejected(self, client, owner_user):
        client.force_login(owner_user)
        client.post(
            reverse("access_add_domain"),
            {"domain": "c.com", "suffix": "has space"},
        )
        assert not AllowedDomain.objects.filter(domain="c.com").exists()


class TestLogoutOnAccessRemoval:
    """Removing a domain/email ends affected users' sessions immediately."""

    def _has_session(self, user):
        return any(
            s.get_decoded().get(SESSION_KEY) == str(user.pk)
            for s in Session.objects.all()
        )

    def _login_with_session(self, user):
        c = Client()
        c.force_login(user)
        c.get(reverse("root"), follow=True)
        return c

    def test_removing_domain_ends_member_sessions(self, client, owner_user):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        member = _make_user("x@example.org")
        self._login_with_session(member)
        assert self._has_session(member)

        d = AllowedDomain.objects.get(domain="example.org")
        client.force_login(owner_user)
        client.post(reverse("access_delete_domain", kwargs={"pk": d.pk}))
        assert not self._has_session(member)

    def test_removing_domain_keeps_still_allowed_user(
        self, client, owner_user
    ):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        AllowedEmail.objects.create(email="keep@example.org")
        member = _make_user("keep@example.org")
        self._login_with_session(member)

        d = AllowedDomain.objects.get(domain="example.org")
        client.force_login(owner_user)
        client.post(reverse("access_delete_domain", kwargs={"pk": d.pk}))
        # Still covered by the individual AllowedEmail → session survives.
        assert self._has_session(member)

    def test_removing_email_ends_session(self, client, owner_user):
        e = AllowedEmail.objects.create(email="solo@gmail.com")
        member = _make_user("solo@gmail.com")
        self._login_with_session(member)
        assert self._has_session(member)

        client.force_login(owner_user)
        client.post(reverse("access_delete_email", kwargs={"pk": e.pk}))
        assert not self._has_session(member)

    def test_removing_domain_clears_outstanding_magic_link(
        self, client, owner_user
    ):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        member = _make_user("z@example.org")
        member.profile.set_magic_token("a-token")
        member.profile.save()

        d = AllowedDomain.objects.get(domain="example.org")
        client.force_login(owner_user)
        client.post(reverse("access_delete_domain", kwargs={"pk": d.pk}))
        member.profile.refresh_from_db()
        assert member.profile.magic_link_token == ""
        assert member.profile.magic_link_expires is None


class TestVerifyRespectsAllowlist:
    """A magic link must not redeem after the user's access is revoked."""

    def test_revoked_link_is_rejected_and_cleared(self, client, db):
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        client.post(reverse("login"), {"email": "alice@example.org"})
        token = re.search(r"token=([^&]+)", mail.outbox[0].body).group(1)

        # Revoke access (delete the row directly, leaving the token intact).
        AllowedDomain.objects.filter(domain="example.org").delete()

        r = client.get(
            reverse("verify"),
            {"token": token, "email": "alice@example.org"},
        )
        assert r.status_code == 302
        assert r.url == reverse("login")
        profile = User.objects.get(username="alice@example.org").profile
        assert profile.magic_link_token == ""  # token killed at redemption


class TestAdminAccessRevocation:
    """Removing allowlist rows via the Django admin also cuts access."""

    def _admin(self, user):
        user.is_staff = True
        user.is_superuser = True
        user.save()
        return user

    def test_admin_domain_delete_ends_sessions(self, client, owner_user):
        # owner_user is the system owner (required to delete a domain).
        self._admin(owner_user)
        AllowedDomain.objects.create(domain="example.org", suffix="ex")
        member = _make_user("y@example.org")
        member_client = Client()
        member_client.force_login(member)
        member_client.get(reverse("root"), follow=True)
        assert _has_active_session(member)

        d = AllowedDomain.objects.get(domain="example.org")
        client.force_login(owner_user)
        client.post(
            reverse("admin:users_alloweddomain_delete", args=[d.pk]),
            {"post": "yes"},
        )
        assert not AllowedDomain.objects.filter(pk=d.pk).exists()
        assert not _has_active_session(member)

    def test_admin_rejects_plus_addressed_email(self, client, owner_user):
        self._admin(owner_user)
        client.force_login(owner_user)
        client.post(
            reverse("admin:users_allowedemail_add"),
            {"email": "mike+x@gmail.com"},
        )
        assert not AllowedEmail.objects.filter(
            email="mike+x@gmail.com"
        ).exists()


class TestAllowedEmailModel:
    def test_clean_rejects_plus_addressing(self, db):
        with pytest.raises(ValidationError):
            AllowedEmail(email="mike+x@gmail.com").full_clean()

    def test_clean_allows_plain_address(self, db):
        # Should not raise.
        AllowedEmail(email="mike@gmail.com").full_clean()


# ── Rate Limiting and 429 Tests ─────────────────────────


class TestRateLimitConfig:
    """SECURITY: verify rate limit infrastructure is properly configured."""

    def test_ratelimit_middleware_installed(self, db):
        """The ratelimit middleware must be in MIDDLEWARE."""
        assert any("RatelimitMiddleware" in m for m in settings.MIDDLEWARE)

    def test_ratelimit_view_configured(self, db):
        """RATELIMIT_VIEW must point to our 429 handler."""
        assert settings.RATELIMIT_VIEW == "wiki.lib.views.ratelimited"

    def test_429_template_renders(self, client, db):
        """The 429 handler returns a 429 status with the error template."""
        request = RequestFactory().get("/")
        response = ratelimited(request)
        assert response.status_code == 429
        assert b"Too Many Requests" in response.content

    def test_csp_middleware_installed(self, db):
        """The CSP middleware must be in MIDDLEWARE."""
        assert any("CSPMiddleware" in m for m in settings.MIDDLEWARE)
