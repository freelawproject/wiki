"""Tests for Sign in with CourtListener (OIDC relying party)."""

from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from wiki.users.auth import CourtListenerOIDCBackend
from wiki.users.models import AllowedEmail, SystemConfig, UserProfile

CLAIMS = {
    "sub": "42",
    "email": "alice@free.law",
    "email_verified": True,
    "name": "Alice Example",
}


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def oidc_enabled(settings):
    settings.OIDC_RP_CLIENT_ID = "wiki-client"
    settings.OIDC_RP_CLIENT_SECRET = "wiki-secret"
    settings.COURTLISTENER_LOGIN_ENABLED = True


@pytest.fixture
def backend(oidc_enabled):
    return CourtListenerOIDCBackend()


def _profile(user):
    return UserProfile.objects.get(user=user)


class TestVerifyClaims:
    @pytest.mark.parametrize(
        "overrides, expected",
        [
            ({}, True),
            ({"email_verified": False}, False),
            ({"email_verified": "true"}, False),
            ({"email": ""}, False),
            ({"sub": ""}, False),
        ],
    )
    def test_requires_sub_and_verified_email(
        self, backend, overrides, expected
    ):
        assert backend.verify_claims({**CLAIMS, **overrides}) is expected


class TestLinking:
    def test_creates_allowed_user(self, backend, db):
        user = backend.create_user(CLAIMS)
        assert user.username == "alice@free.law"
        assert user.email == "alice@free.law"
        profile = _profile(user)
        assert profile.courtlistener_sub == "42"
        assert profile.display_name == "Alice Example"
        assert profile.handle
        assert profile.gravatar_url

    def test_create_normalizes_email(self, backend, db):
        user = backend.create_user({**CLAIMS, "email": " Alice@Free.law "})
        assert user.username == "alice@free.law"

    def test_first_user_becomes_owner(self, backend, db):
        user = backend.create_user(CLAIMS)
        assert SystemConfig.objects.get(pk=1).owner == user
        assert user.is_staff and user.is_superuser

    def test_disallowed_email_not_created(self, backend, db):
        claims = {**CLAIMS, "email": "alice@gmail.com"}
        assert backend.create_user(claims) is None
        assert not User.objects.filter(username="alice@gmail.com").exists()

    def test_links_existing_user_by_email(self, backend, user):
        assert list(backend.filter_users_by_claims(CLAIMS)) == [user]
        assert backend.update_user(user, CLAIMS) == user
        assert _profile(user).courtlistener_sub == "42"

    def test_email_match_is_case_insensitive(self, backend, user):
        claims = {**CLAIMS, "email": "Alice@Free.law"}
        assert list(backend.filter_users_by_claims(claims)) == [user]

    def test_mixed_case_username_rows_are_ignored(self, backend, user):
        upper = User.objects.create_user(
            username="Alice@free.law", email="Alice@free.law"
        )
        UserProfile.objects.create(user=upper)
        assert list(backend.filter_users_by_claims(CLAIMS)) == [user]

    def test_update_user_bootstraps_owner(self, backend, db):
        admin_made = User.objects.create_user(
            username="alice@free.law", email="alice@free.law"
        )
        assert backend.update_user(admin_made, CLAIMS) == admin_made
        admin_made.refresh_from_db()
        assert SystemConfig.objects.get(pk=1).owner == admin_made
        assert admin_made.is_staff and admin_made.is_superuser
        assert _profile(admin_made).courtlistener_sub == "42"
        assert _profile(admin_made).handle

    def test_matches_by_sub_before_email(self, backend, user, other_user):
        profile = _profile(other_user)
        profile.courtlistener_sub = "42"
        profile.save()
        assert list(backend.filter_users_by_claims(CLAIMS)) == [other_user]

    def test_sub_mismatch_rejected(self, backend, user):
        profile = _profile(user)
        profile.courtlistener_sub = "99"
        profile.save()
        assert backend.update_user(user, CLAIMS) is None
        assert _profile(user).courtlistener_sub == "99"

    def test_archived_user_rejected(self, backend, user):
        user.is_active = False
        user.save()
        assert backend.update_user(user, CLAIMS) is None

    def test_revoked_allowlist_rejected(self, backend, db):
        AllowedEmail.objects.create(email="guest@example.org")
        user = backend.create_user({**CLAIMS, "email": "guest@example.org"})
        AllowedEmail.objects.all().delete()
        assert backend.update_user(user, CLAIMS) is None

    def test_existing_display_name_kept(self, backend, user):
        user.profile.display_name = "Chosen Name"
        user.profile.save()
        backend.update_user(user, CLAIMS)
        assert _profile(user).display_name == "Chosen Name"

    def test_get_or_create_user_links_via_userinfo(
        self, backend, user, monkeypatch
    ):
        monkeypatch.setattr(
            backend, "get_userinfo", lambda *args: dict(CLAIMS)
        )
        assert backend.get_or_create_user("access", "id", {}) == user
        assert _profile(user).courtlistener_sub == "42"

    def test_get_or_create_user_rejects_unverified(
        self, backend, user, monkeypatch
    ):
        claims = {**CLAIMS, "email_verified": False}
        monkeypatch.setattr(backend, "get_userinfo", lambda *args: claims)
        with pytest.raises(Exception, match="Claims verification failed"):
            backend.get_or_create_user("access", "id", {})


class TestLoginPage:
    def test_button_shown_when_enabled(self, client, db, oidc_enabled):
        r = client.get(reverse("login"))
        assert b"Sign in with CourtListener" in r.content
        assert reverse("oidc_authentication_init").encode() in r.content
        assert b"Send Sign-In Link" in r.content

    def test_button_hidden_when_disabled(self, client, db, settings):
        settings.COURTLISTENER_LOGIN_ENABLED = False
        r = client.get(reverse("login"))
        assert b"Sign in with CourtListener" not in r.content

    def test_button_carries_next(self, client, db, oidc_enabled):
        r = client.get(reverse("login"), {"next": "/c/engineering/"})
        assert b"courtlistener/?next=/c/engineering/" in r.content


class TestInitView:
    def test_404_when_disabled(self, client, db, settings):
        settings.COURTLISTENER_LOGIN_ENABLED = False
        r = client.get(reverse("oidc_authentication_init"))
        assert r.status_code == 404

    def test_redirects_to_courtlistener_with_pkce(
        self, client, db, oidc_enabled, settings
    ):
        r = client.get(
            reverse("oidc_authentication_init"), {"next": "/c/engineering/"}
        )
        assert r.status_code == 302
        parsed = urlparse(r.url)
        assert r.url.startswith(settings.OIDC_OP_AUTHORIZATION_ENDPOINT)
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["wiki-client"]
        assert params["response_type"] == ["code"]
        assert params["scope"] == ["openid email profile"]
        assert params["code_challenge_method"] == ["S256"]
        assert params["code_challenge"]
        assert params["nonce"]
        assert params["redirect_uri"][0].endswith(
            reverse("oidc_authentication_callback")
        )
        assert params["state"][0] in client.session["oidc_states"]
        assert client.session["oidc_login_next"] == "/c/engineering/"

    def test_rate_limited_per_ip(self, client, db, oidc_enabled, settings):
        settings.RATELIMIT_ENABLE = True
        cache.clear()
        statuses = [
            client.get(reverse("oidc_authentication_init")).status_code
            for _ in range(11)
        ]
        assert statuses[:10] == [302] * 10
        assert statuses[10] == 429

    def test_offsite_next_dropped(self, client, db, oidc_enabled):
        client.get(
            reverse("oidc_authentication_init"),
            {"next": "https://evil.example/"},
        )
        assert client.session["oidc_login_next"] is None


class TestCallbackView:
    def _start(self, client, next_url=None):
        params = {"next": next_url} if next_url else {}
        r = client.get(reverse("oidc_authentication_init"), params)
        return parse_qs(urlparse(r.url).query)["state"][0]

    def _fake_exchange(self, monkeypatch, claims):
        monkeypatch.setattr(
            CourtListenerOIDCBackend,
            "get_token",
            lambda self, payload: {"id_token": "idt", "access_token": "at"},
        )
        monkeypatch.setattr(
            CourtListenerOIDCBackend,
            "verify_token",
            lambda self, token, **kwargs: {"sub": claims["sub"]},
        )
        monkeypatch.setattr(
            CourtListenerOIDCBackend,
            "get_userinfo",
            lambda self, *args: dict(claims),
        )

    def test_404_when_disabled(self, client, db, settings):
        settings.COURTLISTENER_LOGIN_ENABLED = False
        r = client.get(reverse("oidc_authentication_callback"))
        assert r.status_code == 404

    def test_success_provisions_and_logs_in(
        self, client, db, oidc_enabled, monkeypatch
    ):
        state = self._start(client, "/c/engineering/")
        self._fake_exchange(monkeypatch, CLAIMS)
        r = client.get(
            reverse("oidc_authentication_callback"),
            {"code": "abc", "state": state},
        )
        assert r.status_code == 302
        assert r.url == "/c/engineering/"
        user = User.objects.get(username="alice@free.law")
        assert client.session[SESSION_KEY] == str(user.pk)
        assert _profile(user).courtlistener_sub == "42"

    def test_disallowed_email_fails_to_login_page(
        self, client, db, oidc_enabled, monkeypatch
    ):
        state = self._start(client)
        self._fake_exchange(monkeypatch, {**CLAIMS, "email": "a@gmail.com"})
        r = client.get(
            reverse("oidc_authentication_callback"),
            {"code": "abc", "state": state},
        )
        assert r.status_code == 302
        assert r.url == reverse("login")
        assert SESSION_KEY not in client.session
        assert not User.objects.filter(username="a@gmail.com").exists()

    def test_provider_error_fails_to_login_page(
        self, client, db, oidc_enabled
    ):
        state = self._start(client)
        r = client.get(
            reverse("oidc_authentication_callback"),
            {"error": "access_denied", "state": state},
        )
        assert r.status_code == 302
        assert r.url == reverse("login")

    def test_unknown_state_rejected(self, client, db, oidc_enabled):
        self._start(client)
        r = client.get(
            reverse("oidc_authentication_callback"),
            {"code": "abc", "state": "forged"},
        )
        assert r.status_code == 400
