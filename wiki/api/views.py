"""Read-only JSON API over wiki content.

This is the data layer the CourtListener MCP server's wiki tools call
(freelawproject/courtlistener-api-client, ``courtlistener/mcp/tools/``).
It deliberately speaks plain JSON, not MCP: the MCP protocol surface
lives in the MCP server, and the wiki only exposes permission-scoped
data that any client could consume.

Auth: anonymous requests see public pages. Requests bearing a
CourtListener OAuth token (``Authorization: Bearer …``) act as the wiki
account mapped from that token — see ``wiki/lib/cl_oauth.py``. A
browser session works too, which makes the endpoints easy to poke at
while logged in.

No new permission logic: listing filters with ``viewable_pages_q()``,
reads check ``can_view_page()``, and search runs through
``search_pages()`` — the same functions the HTML views use, so
permission changes propagate here automatically.

Responses are marked ``private, no-store``: bearer-token requests carry
no session cookie, so without this a CDN could mistake a personalized
response for anonymous content and cache it.
"""

import re

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from wiki.lib.cache_headers import PRIVATE_CACHE_CONTROL
from wiki.lib.cl_oauth import user_for_bearer_token
from wiki.lib.page_utils import page_at_path, slug_redirect_at_path
from wiki.lib.permissions import can_view_page, viewable_pages_q
from wiki.pages.models import Page
from wiki.pages.search import search_pages
from wiki.pages.search_parser import parse_query

MAX_SEARCH_RESULTS = 10

_MARK_TAG_RE = re.compile(r"</?mark>")


def _request_user(request):
    """Resolve the acting user: bearer token first, then session."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return user_for_bearer_token(auth[len("Bearer ") :])
    return request.user


def _json(payload, status=200):
    """JsonResponse that opts out of CDN/browser caching."""
    response = JsonResponse(payload, status=status)
    response.headers["Cache-Control"] = PRIVATE_CACHE_CONTROL
    return response


def _not_found():
    """Identical response for missing and forbidden paths.

    Keeps the API from being probed for the existence of private pages,
    mirroring the ``.md`` endpoint's 404 behavior.
    """
    return _json({"error": "not_found"}, status=404)


def _page_url(page):
    return f"{settings.BASE_URL}{page.get_absolute_url()}"


def _page_summary(page):
    return {
        "title": page.title,
        "path": page.content_path,
        "url": _page_url(page),
        "updated_at": page.updated_at.isoformat(),
    }


@require_GET
def list_pages(request):
    """List every page the acting user can view.

    Optional ``?directory=<path>`` restricts results to that directory
    and its descendants.
    """
    user = _request_user(request)
    qs = (
        Page.objects.filter(viewable_pages_q(user))
        .select_related("directory")
        .order_by("directory__path", "slug")
    )
    if directory := request.GET.get("directory", "").strip().strip("/"):
        qs = qs.filter(
            Q(directory__path=directory)
            | Q(directory__path__startswith=f"{directory}/")
        )

    pages = [
        _page_summary(page) | {"description": page.seo_description or ""}
        for page in qs
    ]
    return _json({"count": len(pages), "pages": pages})


@require_GET
def read_page(request, path):
    """Return one page's markdown, following slug redirects."""
    user = _request_user(request)
    clean = path.strip("/")
    if clean.endswith(".md"):
        clean = clean[: -len(".md")]

    page = page_at_path(clean)
    if page is None and (redirect := slug_redirect_at_path(clean)):
        page = redirect.page
    if page is None or not can_view_page(user, page):
        return _not_found()

    return _json(
        _page_summary(page) | {"markdown": f"# {page.title}\n\n{page.content}"}
    )


@require_GET
def search(request):
    """Full-text search, top results with highlighted snippets.

    ``?q=`` supports the wiki's advanced syntax (``title:``, ``in:``,
    ``before:``/``after:``, ``-word``, quoted phrases) via
    ``parse_query`` — inherited for free from the HTML search.
    """
    user = _request_user(request)
    query = request.GET.get("q", "").strip()
    if not query:
        return _json({"error": "missing_query"}, status=400)

    qs, total = search_pages(parse_query(query), user)
    results = [
        _page_summary(page)
        | {
            "snippet": _MARK_TAG_RE.sub(
                "", getattr(page, "headline", "") or ""
            )
        }
        for page in qs[:MAX_SEARCH_RESULTS]
    ]
    return _json({"count": total, "results": results})
