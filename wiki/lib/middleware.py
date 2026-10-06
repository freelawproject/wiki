"""SEO and abuse-protection middleware."""

from django.urls import Resolver404, resolve
from django_ratelimit.core import is_ratelimited

from wiki.lib.ratelimiter import GLOBAL_WRITE_RATES, get_ratelimit_ident
from wiki.lib.views import ratelimited

# Paths that should always get noindex/nofollow headers regardless
# of content visibility.
_NOINDEX_PREFIXES = (
    "/admin/",
    "/api/",
    "/u/",
    "/search/",
    "/files/",
    "/unsubscribe/",
)


class SEOHeadersMiddleware:
    """Add X-Robots-Tag and Link canonical headers to responses.

    Views can set two attributes on the request object:
      - ``request.seo_noindex = True`` — emit ``X-Robots-Tag: noindex, nofollow``
      - ``request.seo_canonical = "/c/some-page"`` — emit a ``Link: <url>; rel="canonical"`` header
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Always noindex non-content paths
        if request.path.startswith(_NOINDEX_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow"
            return response

        # Views may flag non-public content for noindex
        if getattr(request, "seo_noindex", False):
            response["X-Robots-Tag"] = "noindex, nofollow"

        # Views may set a canonical URL
        canonical = getattr(request, "seo_canonical", None)
        if canonical:
            response["Link"] = f'<{canonical}>; rel="canonical"'

        return response


# Fire-and-forget endpoints that JS calls on page loads or while editing.
# They have their own, higher limits, so a person reading or editing can't
# trip the global write cap by simply using the site.
_GLOBAL_LIMIT_EXEMPT_URL_NAMES = frozenset(
    {"page_preview", "record_page_view"}
)


class GlobalWriteRateLimitMiddleware:
    """Cap anonymous state-changing requests (POST, PUT, PATCH, DELETE).

    A blanket backstop behind the tighter per-view limits in
    ``wiki.lib.ratelimiter``, so scanners hammering any endpoint —
    including views that have no decorator — get a 429.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._exempt(request):
            return self.get_response(request)

        # Every rate is checked (and counted) so each window stays accurate.
        limited = [
            is_ratelimited(
                request,
                group=f"global-writes-{rate.replace('/', '-')}",
                key=get_ratelimit_ident,
                rate=rate,
                method=["POST", "PUT", "PATCH", "DELETE"],
                increment=True,
            )
            for rate in GLOBAL_WRITE_RATES
        ]
        if any(limited):
            return ratelimited(request)
        return self.get_response(request)

    @staticmethod
    def _exempt(request):
        # The cap targets anonymous scanners; signed-in users are accounted
        # for and still subject to the per-view limits.
        if request.user.is_authenticated:
            return True
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return False
        return match.url_name in _GLOBAL_LIMIT_EXEMPT_URL_NAMES
