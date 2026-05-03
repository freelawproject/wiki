"""Tests for the CDN cache-header decorator + middleware pair.

The unit tests for behavior must run the request through the middleware
chain, not just the decorator alone — the decorator is a marker, the
real logic lives in ``AnonymousCacheHeadersMiddleware``.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory

from wiki.lib.cache_headers import (
    ANON_CACHE_CONTROL,
    PRIVATE_CACHE_CONTROL,
    AnonymousCacheHeadersMiddleware,
    cache_for_anonymous,
)


@cache_for_anonymous
def _ok_view(request):
    return HttpResponse("ok")


@cache_for_anonymous
def _redirect_view(request):
    return HttpResponseRedirect("/elsewhere/")


@cache_for_anonymous
def _preset_view(request):
    response = HttpResponse("ok")
    response["Cache-Control"] = "public, max-age=99"
    return response


@cache_for_anonymous
def _vary_already_view(request):
    response = HttpResponse("ok")
    response["Vary"] = "Accept-Encoding"
    return response


@cache_for_anonymous
def _cookie_setting_view(request):
    response = HttpResponse("ok")
    response.set_cookie("messages", "your comment was submitted")
    return response


def _undecorated_ok_view(request):
    return HttpResponse("ok")


def _run(view, request):
    """Run the view through ``AnonymousCacheHeadersMiddleware``."""
    middleware = AnonymousCacheHeadersMiddleware(view)
    return middleware(request)


def _anon_request(method="GET"):
    rf = RequestFactory()
    request = getattr(rf, method.lower())("/")
    request.user = AnonymousUser()
    return request


def _auth_request(method="GET"):
    rf = RequestFactory()
    request = getattr(rf, method.lower())("/")

    class _U:
        is_authenticated = True

    request.user = _U()
    return request


def test_anonymous_get_gets_public_cache_control():
    response = _run(_ok_view, _anon_request())
    assert response["Cache-Control"] == ANON_CACHE_CONTROL
    assert "Cookie" in response["Vary"]


def test_authenticated_request_gets_private_cache_control():
    response = _run(_ok_view, _auth_request())
    assert response["Cache-Control"] == PRIVATE_CACHE_CONTROL
    assert "Cookie" in response["Vary"]


def test_post_response_left_alone():
    """Non-GET responses aren't CDN-cacheable, so the middleware passes
    them through untouched — no Cache-Control, no Vary."""
    for request in (_anon_request("POST"), _auth_request("POST")):
        response = _run(_ok_view, request)
        assert "Cache-Control" not in response.headers
        assert "Vary" not in response.headers


def test_anonymous_redirect_left_alone():
    """A 302 from a marked view is non-2xx — middleware must NOT stamp a
    public TTL on a redirect."""
    response = _run(_redirect_view, _anon_request())
    assert "Cache-Control" not in response.headers


def test_existing_cache_control_not_overridden():
    response = _run(_preset_view, _anon_request())
    assert response["Cache-Control"] == "public, max-age=99"


def test_vary_appends_cookie_without_clobbering():
    response = _run(_vary_already_view, _anon_request())
    parts = [p.strip() for p in response["Vary"].split(",")]
    assert "Accept-Encoding" in parts
    assert "Cookie" in parts


def test_vary_does_not_duplicate_cookie():
    @cache_for_anonymous
    def view(request):
        response = HttpResponse("ok")
        response["Vary"] = "Cookie, Accept-Encoding"
        return response

    response = _run(view, _anon_request())
    parts = [p.strip().lower() for p in response["Vary"].split(",")]
    assert parts.count("cookie") == 1


def test_response_with_set_cookie_is_not_cached():
    """Defense against flash-message leaks.

    If a marked view (or a downstream middleware like Django messages)
    sets a cookie on the response, that cookie carries per-visitor
    state. Caching it and replaying it to other anonymous visitors
    would leak the user's flash. The middleware drops to ``private,
    no-store`` whenever any cookie is on the response.
    """
    response = _run(_cookie_setting_view, _anon_request())
    assert response["Cache-Control"] == PRIVATE_CACHE_CONTROL


def test_undecorated_view_left_alone():
    """Views not marked with ``cache_for_anonymous`` get no headers from
    the middleware, regardless of method or auth state."""
    for request in (_anon_request(), _auth_request(), _anon_request("POST")):
        response = _run(_undecorated_ok_view, request)
        assert "Cache-Control" not in response.headers
        assert "Vary" not in response.headers


# --- Integration tests via the test client (real middleware chain) ---


@pytest.mark.django_db
def test_anonymous_root_response_has_no_set_cookie(client):
    """Cacheable responses must never emit Set-Cookie. Regression for
    csrf_token in template, session writes, Waffle flag rollout."""
    response = client.get("/")
    assert "Set-Cookie" not in response.headers, (
        f"Unexpected Set-Cookie on /: {response.headers.get('Set-Cookie')}"
    )


@pytest.mark.django_db
def test_anonymous_llms_txt_has_no_set_cookie(client):
    response = client.get("/llms.txt")
    assert "Set-Cookie" not in response.headers


@pytest.mark.django_db
def test_anonymous_robots_txt_has_no_set_cookie(client):
    response = client.get("/robots.txt")
    assert "Set-Cookie" not in response.headers


@pytest.mark.django_db
def test_anonymous_sitemap_has_no_set_cookie(client):
    response = client.get("/sitemap.xml")
    assert "Set-Cookie" not in response.headers


@pytest.mark.django_db
def test_anonymous_page_view_endpoint_has_no_set_cookie(client, page):
    response = client.post(
        "/api/page-view/",
        data='{"page_id": ' + str(page.id) + "}",
        content_type="application/json",
    )
    assert "Set-Cookie" not in response.headers


@pytest.mark.django_db
def test_anonymous_root_response_has_public_cache_control(client):
    response = client.get("/")
    assert response.headers.get("Cache-Control") == ANON_CACHE_CONTROL


@pytest.mark.django_db
def test_stale_sessionid_cookie_yields_private_no_store(client):
    """Regression: cache middleware must run AFTER SessionMiddleware on
    the response chain.

    If an anonymous request arrives with a ``sessionid`` cookie that
    doesn't match a real session, Django's ``SessionMiddleware`` emits
    a delete-sessionid ``Set-Cookie`` on the response. That Set-Cookie
    is per-visitor state — caching the response would replay the
    delete-cookie (and the HTML around it) to other anonymous visitors.

    For the cache middleware to see that Set-Cookie, its response phase
    must run LAST, which means it must sit at the TOP of MIDDLEWARE.
    Before this fix, it sat below ``SessionMiddleware``, so the delete
    cookie was attached AFTER the cache middleware had already stamped
    ``public, s-maxage=2592000``. CloudFront would then cache it.
    """
    client.cookies["sessionid"] = "stale-fake-session-key-aaaaaa"
    response = client.get("/")
    # Sanity check: SessionMiddleware did emit a delete-cookie.
    assert "sessionid" in response.cookies, (
        "test setup assumption broken: SessionMiddleware did not emit a "
        "delete-sessionid cookie for a stale incoming sessionid"
    )
    assert response.headers.get("Cache-Control") == PRIVATE_CACHE_CONTROL, (
        f"Cacheable response with a Set-Cookie attached! Got: "
        f"{response.headers.get('Cache-Control')}"
    )


@pytest.mark.django_db
def test_messages_framework_does_not_poison_cache(client, page):
    """End-to-end leak test:

    Anonymous user submits a comment via ``/c/<page>/feedback/`` →
    ``messages.success`` adds a flash → 302 to ``/c/<page>`` →
    browser follows with the ``messages`` cookie → page renders
    "Your comment has been submitted." into HTML → MessageMiddleware
    deletes the cookie via Set-Cookie. The response *must* end up with
    ``Cache-Control: private, no-store`` so CloudFront doesn't cache
    the leaked flash.
    """
    # Submit a comment as anonymous.
    response = client.post(
        f"/c/{page.content_path}/feedback/",
        {
            "submit_comment": "1",
            "message": "Test comment",
            "name": "Anon",
            "email": "a@b.com",
        },
        follow=False,
    )
    assert response.status_code == 302
    # The redirect must have set the messages cookie.
    assert "messages" in response.cookies, (
        "page_feedback POST must produce a messages cookie for this test"
    )

    # Follow the redirect — the response should NOT be cacheable.
    landing = client.get(response.headers["Location"])
    assert landing.status_code == 200
    body = landing.content.decode()
    assert "comment has been submitted" in body, (
        "test setup didn't actually trigger the flash render"
    )
    assert landing.headers.get("Cache-Control") == PRIVATE_CACHE_CONTROL, (
        f"Cacheable response with leaked flash! Got: "
        f"{landing.headers.get('Cache-Control')}"
    )
