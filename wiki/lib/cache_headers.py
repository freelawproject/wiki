"""Cache-Control header logic for CDN-fronted views.

The wiki sits behind CloudFront, which caches anonymous (no ``sessionid``
cookie) GETs of public content. Views that should be CDN-cacheable are
marked with the :func:`cache_for_anonymous` decorator. The actual
``Cache-Control``/``Vary`` decision is deferred to
:class:`AnonymousCacheHeadersMiddleware`, which runs after every other
response-phase middleware — including ``CsrfViewMiddleware`` and
``MessageMiddleware``, both of which can attach ``Set-Cookie`` headers
that would carry per-visitor state into a cached response.

If we made the decision inside the decorator (i.e. before the rest of
the middleware chain processes the response), we'd miss those late-set
cookies and silently cache them. The middleware sees the final
response and can drop to ``private, no-store`` whenever any cookie is
about to be sent.
"""

from functools import wraps

# 30 seconds in browsers; 30 days at the CDN. The CDN value is high
# because we invalidate on every change. The browser value is low so a
# user who lingers sees an edit reasonably quickly even if invalidation
# propagation is on the slow side.
ANON_CACHE_CONTROL = "public, max-age=30, s-maxage=2592000"
PRIVATE_CACHE_CONTROL = "private, no-store"

# Attribute set by the decorator to opt the response in. Read by the
# middleware. Anything not marked is left alone.
_MARKER_ATTR = "_cache_for_anonymous"


def cache_for_anonymous(view_func):
    """Mark a view's response as eligible for anonymous CDN caching.

    The actual ``Cache-Control``/``Vary`` decision happens in
    :class:`AnonymousCacheHeadersMiddleware`, which runs after every
    other response-phase middleware so it sees ``Set-Cookie`` headers
    written by ``MessageMiddleware``, ``CsrfViewMiddleware``, etc.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        setattr(response, _MARKER_ATTR, True)
        return response

    return wrapper


class AnonymousCacheHeadersMiddleware:
    """Finalize cache headers for views marked by ``cache_for_anonymous``.

    Must be installed at the *top* of MIDDLEWARE so its response phase
    runs LAST — i.e. after every other middleware that might attach a
    ``Set-Cookie`` header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(response, _MARKER_ATTR, False):
            return response
        if request.method not in ("GET", "HEAD"):
            # Non-GET/HEAD aren't CDN-cacheable; don't clutter headers.
            return response

        _patch_vary(response)

        if request.user.is_authenticated:
            response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
            return response
        if not (200 <= response.status_code < 300):
            return response
        if response.has_header("Cache-Control"):
            # View / earlier middleware set its own policy — respect it.
            return response
        if response.cookies:
            # Anything that emits Set-Cookie (Django messages on a
            # post-redirect-get, a freshly minted CSRF cookie, a
            # gradual-rollout Waffle cookie) carries per-visitor state.
            # Caching this response would replay the cookie and the
            # personalized HTML it implies to subsequent anonymous
            # visitors.
            response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
            return response
        response.headers["Cache-Control"] = ANON_CACHE_CONTROL
        return response


def _patch_vary(response):
    existing = response.headers.get("Vary", "")
    parts = [p.strip() for p in existing.split(",") if p.strip()]
    if not any(p.lower() == "cookie" for p in parts):
        parts.append("Cookie")
        response.headers["Vary"] = ", ".join(parts)
