"""Tests for CourtListener bearer auth."""

import json

import httpx
import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.http import JsonResponse
from django.test import RequestFactory

from wiki.api import auth
from wiki.api.auth import bearer_auth


@bearer_auth
def whoami(request):
    return JsonResponse({"user": request.user.get_username()})


def call(token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    request = RequestFactory().get("/", **headers)
    request.user = AnonymousUser()
    return whoami(request)


def who(token=None):
    return json.loads(call(token).content)["user"]


@pytest.fixture(autouse=True)
def _fresh_token_cache(db):
    cache.clear()


@pytest.fixture
def identify(monkeypatch):
    """Stand in for CourtListener: a map of bearer tokens to emails."""
    tokens = {}
    monkeypatch.setattr(auth, "cached_verified_email_for", tokens.get)
    return tokens


class TestBearerAuth:
    def test_no_token_leaves_the_request_user(self, db):
        r = call()
        assert json.loads(r.content) == {"user": ""}
        assert r["Cache-Control"].startswith("max-age=0, no-cache")

    def test_bad_token_is_401(self, db, identify):
        r = call("x")
        assert r.status_code == 401
        assert r["WWW-Authenticate"] == "Bearer"

    def test_allowlisted_email_mints_an_account(self, owner_user, identify):
        identify["t"] = "new@free.law"
        assert who("t") == "new@free.law"
        minted = User.objects.get(username="new@free.law")
        assert minted.profile.handle == "new"
        # Its first use counts as its sign-in; later uses leave that alone.
        first = minted.last_login
        assert first is not None
        who("t")
        assert User.objects.get(pk=minted.pk).last_login == first

    def test_unlisted_email_is_anonymous_without_an_account(
        self, db, identify
    ):
        identify["t"] = "someone@gmail.com"
        assert who("t") == ""
        assert not User.objects.filter(username="someone@gmail.com").exists()

    def test_archived_account_is_anonymous(self, user, identify):
        user.is_active = False
        user.save()
        identify["t"] = user.email
        assert who("t") == ""

    def test_courtlistener_outage_is_a_503(self, settings, db, monkeypatch):
        settings.COURTLISTENER_CLIENT_ID = "wiki"
        settings.COURTLISTENER_CLIENT_SECRET = "secret"

        def down(request):
            raise httpx.ConnectError("refused")

        real = httpx.Client
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kw: real(transport=httpx.MockTransport(down), **kw),
        )
        assert call("t").status_code == 503

    def test_bearer_tokens_are_rejected_until_the_client_is_configured(
        self, settings, db, caplog
    ):
        settings.COURTLISTENER_CLIENT_ID = ""
        assert call("t").status_code == 401
        assert "unset" in caplog.text


@pytest.mark.parametrize(
    "introspection, claims, email",
    [
        (
            {
                "active": True,
                "scope": "openid wiki email",
                "exp": 4_000_000_000,
            },
            {"email": "A@free.law", "email_verified": True},
            "a@free.law",
        ),
        (
            {
                "active": True,
                "scope": "openid wiki email",
                "exp": 4_000_000_000,
            },
            {"email": "a@free.law", "email_verified": False},
            None,
        ),
        (
            {"active": True, "scope": "openid email", "exp": 4_000_000_000},
            {"email": "a@free.law", "email_verified": True},
            None,
        ),
        (
            {"active": True, "scope": "wiki", "exp": 4_000_000_000},
            403,
            None,
        ),
        ({"active": False}, None, None),
    ],
)
def test_verified_email_for(
    settings, monkeypatch, introspection, claims, email
):
    settings.COURTLISTENER_URL = "https://cl.test"
    settings.COURTLISTENER_CLIENT_ID = "wiki"
    settings.COURTLISTENER_CLIENT_SECRET = "secret"

    def handler(request):
        if request.url.path == "/o/introspect/":
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json=introspection)
        assert claims is not None, "userinfo must not be called"
        assert request.headers["Authorization"] == "Bearer tok"
        if isinstance(claims, int):
            return httpx.Response(claims)
        return httpx.Response(200, json=claims)

    real = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    assert auth.verified_email_for("tok")[0] == email


def test_courtlistener_is_asked_once_per_token(settings, monkeypatch):
    settings.COURTLISTENER_CLIENT_ID = "wiki"
    settings.COURTLISTENER_CLIENT_SECRET = "secret"
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/o/introspect/":
            if b"token=bad" in request.content:
                return httpx.Response(200, json={"active": False})
            return httpx.Response(
                200,
                json={"active": True, "scope": "wiki", "exp": 4_000_000_000},
            )
        return httpx.Response(
            200, json={"email": "a@free.law", "email_verified": True}
        )

    real = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    assert auth.cached_verified_email_for("tok") == "a@free.law"
    assert auth.cached_verified_email_for("tok") == "a@free.law"
    assert auth.cached_verified_email_for("bad") is None
    assert auth.cached_verified_email_for("bad") is None
    assert calls == ["/o/introspect/", "/o/userinfo/", "/o/introspect/"]
