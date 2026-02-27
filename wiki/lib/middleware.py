"""SEO-related middleware."""

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
