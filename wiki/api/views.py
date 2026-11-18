"""JSON API for machine clients such as the CourtListener MCP server.

Reading: anyone sees public pages; a CourtListener bearer token sees what
that account's email can see (see ``auth``). A page's ``content`` is the
Markdown readers see by default: data placeholders filled and wiki links
resolved for the caller, so its links are ordinary ``/c/...`` paths.
``?raw=true`` returns the stored source instead, wiki syntax and all.

Writing: ``POST pages/`` creates a page and ``PATCH pages/<path>`` edits one.
Both take a JSON body and need a bearer token whose account (see ``auth``:
the ``wiki`` scope names it) may edit the target; a session cookie is never
enough, so the endpoints skip CSRF. Writes work on the stored source: an
edit sends the page's whole new source (what ``?raw=true`` returns, edited),
and write responses return the stored source. An edit names the revision it was
based on and is refused with a 409 if the page has moved on since, or if
someone holds the page's edit lock in the web editor.
"""

import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from wiki.api.auth import WIKI_SCOPES, bearer_auth, bearer_challenge
from wiki.directories.models import Directory
from wiki.lib.data_source import (
    MIN_TTL,
    content_with_data,
    page_content_with_data,
    validate_data_source_ttl,
    validate_data_source_url,
)
from wiki.lib.edit_lock import get_active_lock_for_page
from wiki.lib.markdown import render_markdown, resolve_wiki_links
from wiki.lib.page_saves import (
    EditConflict,
    current_revision_number,
    save_new_page,
    save_page_edit,
)
from wiki.lib.page_utils import page_at_path
from wiki.lib.permissions import (
    can_edit_directory,
    can_edit_page,
    can_view_directory,
    can_view_page,
    viewable_pages_q,
)
from wiki.lib.ratelimiter import ratelimit_api, ratelimit_api_write
from wiki.lib.seo import extract_description
from wiki.lib.users import display_name
from wiki.pages.models import Page
from wiki.pages.search import search_pages
from wiki.pages.search_parser import parse_query


def _summary(page):
    return {
        "path": page.content_path,
        "title": page.title,
        "description": page.seo_description
        or extract_description(page.content),
        "updated_at": page.updated_at,
    }


def _detail(page, user, revision, content=None, status=200):
    """A page with its content (the stored source unless ``content`` is
    given), the number of the revision that content is from (the
    ``base_revision`` an edit must name) and whether ``user`` may edit it.
    An editor also gets the page's data source, as the web editor shows it."""
    can_edit = can_edit_page(user, page)
    body = {
        **_summary(page),
        "content": page.content if content is None else content,
        "revision": revision,
        "can_edit": can_edit,
    }
    if can_edit:
        body["data_source_url"] = page.data_source_url
        body["data_source_ttl"] = page.data_source_ttl
    return JsonResponse(body, status=status)


def _error(status, error, detail=None, **extra):
    body = {"error": error, **extra}
    if detail:
        body["detail"] = detail
    return JsonResponse(body, status=status)


def _paginated(request, queryset, per_page, key, item):
    """The ``?page=`` of ``queryset`` under ``key``, ``item`` applied to each."""
    page = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    return JsonResponse(
        {
            "total": page.paginator.count,
            "page": page.number,
            "next_page": page.next_page_number() if page.has_next() else None,
            key: [item(p) for p in page],
        }
    )


@csrf_exempt
@ratelimit_api
@require_http_methods(["GET", "POST"])
@bearer_auth
def page_list(request):
    if request.method == "POST":
        return _create_page(request)
    pages = (
        Page.objects.filter(viewable_pages_q(request.user))
        .select_related("directory")
        .order_by("directory__path", "title", "pk")
        .distinct()
    )
    return _paginated(
        request, pages, settings.PAGE_LIST_RESULTS_PER_PAGE, "pages", _summary
    )


@csrf_exempt
@ratelimit_api
@require_http_methods(["POST"])
@bearer_auth
def preview(request):
    """Render page source to HTML as the page view would, without saving
    anything: the API's counterpart of the editor's Preview tab.

    The JSON body has the Markdown ``content`` and, optionally, the
    ``data_source_url`` to fill its placeholders from. Its response is
    cached for only the shortest time a page's may be, so a preview shows
    current data. Like the editor's preview it's open to anyone, and renders as
    the caller, so wiki links to pages the caller can't see stay
    unresolved. Filling placeholders makes the server fetch the given URL,
    so a data source needs what setting one on a page needs: an account
    that may write, held to the write rate limit.
    """
    try:
        body = _json_body(request)
        content = _text(body, "content", required=True, blank=True)
        url = _data_source_url(body)
    except BadRequest as e:
        return _error(400, "invalid_request", str(e))
    if url and (denied := _write_denied(request)):
        return denied
    html = render_markdown(
        content_with_data(content, url, MIN_TTL), viewer=request.user
    )
    return JsonResponse({"html": str(html)})


@ratelimit_api
@require_GET
@bearer_auth
def page_search(request):
    pages = search_pages(parse_query(request.GET.get("q", "")), request.user)
    return _paginated(
        request,
        pages,
        settings.SEARCH_RESULTS_PER_PAGE,
        "results",
        lambda p: {**_summary(p), "snippet": strip_tags(p.headline)},
    )


@csrf_exempt
@ratelimit_api
@require_http_methods(["GET", "PATCH"])
@bearer_auth
def page_detail(request, path):
    # A write is refused for want of a usable token before the page is
    # looked up, so the caller gets the 401 or 403 challenge rather than a
    # 404 for a page it can't see yet. It doesn't depend on the page.
    if request.method == "PATCH" and (denied := _write_denied(request)):
        return denied
    page = page_at_path(path.strip("/"))
    if page is None or not can_view_page(request.user, page):
        return _error(404, "not_found")
    if request.method == "PATCH":
        return _update_page(request, page)
    # Read the revision number before the content, so the content is never
    # older than the revision it's reported as: an edit made from it can at
    # worst be refused as a conflict, never overwrite a newer edit.
    revision = current_revision_number(page)
    page.refresh_from_db()
    if request.GET.get("raw", "").lower() in ("1", "true"):
        content = page.content
    else:
        # A link to a page the caller can't see stays as written, without
        # the web's not-found HTML.
        content = resolve_wiki_links(
            page_content_with_data(page),
            viewer=request.user,
            mark_missing=False,
        )
    return _detail(page, request.user, revision, content=content)


class BadRequest(Exception):
    """A write's JSON body is malformed; the message says how."""


def _write_denied(request):
    """Why ``request`` may not write at all, as an error response, or None.

    ``bearer_auth`` has already turned away a token CourtListener rejects
    and made ``request.user`` the token's account, if it names one.
    """
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return JsonResponse(
            {"error": "invalid_token"},
            status=401,
            headers={"WWW-Authenticate": bearer_challenge()},
        )
    if ratelimit_api_write(request):
        return _error(429, "ratelimited")
    if getattr(request, "bearer_missing_scopes", False):
        return JsonResponse(
            {
                "error": "insufficient_scope",
                "detail": "Editing needs a token with the "
                f"`{' '.join(WIKI_SCOPES)}` scopes.",
            },
            status=403,
            headers={
                "WWW-Authenticate": bearer_challenge("insufficient_scope")
            },
        )
    if not request.user.is_authenticated:
        return _error(
            403,
            "forbidden",
            "This token's account has no access to the wiki.",
        )
    return None


def _json_body(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError as e:
        raise BadRequest("The body must be JSON.") from e
    if not isinstance(body, dict):
        raise BadRequest("The body must be a JSON object.")
    return body


def _text(body, field, *, required=False, max_length=None, blank=False):
    """``body[field]`` as a string, stripped unless it's page content."""
    value = body.get(field)
    if value is None:
        if required:
            raise BadRequest(f"`{field}` is required.")
        return None
    if not isinstance(value, str):
        raise BadRequest(f"`{field}` must be a string.")
    if field != "content":
        value = value.strip()
    # Postgres can't store a NUL, and a lone surrogate isn't valid UTF-8.
    if "\x00" in value:
        raise BadRequest(f"`{field}` can't contain NUL characters.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as e:
        raise BadRequest(f"`{field}` isn't valid Unicode.") from e
    if not value and not blank:
        raise BadRequest(f"`{field}` can't be empty.")
    if max_length and len(value) > max_length:
        raise BadRequest(f"`{field}` is longer than {max_length} characters.")
    return value


def _data_source(body):
    """The data source settings in ``body``, as ``{field: value}`` for the
    fields it sends, checked with the web editor's own check.
    ``data_source_url`` is a URL on the data source allowlist, or ``""`` (or
    null) to remove the data source; ``data_source_ttl`` is how many seconds
    to cache its response, from 10 to a day."""
    fields = {}
    if "data_source_url" in body:
        fields["data_source_url"] = _data_source_url(body)
    if "data_source_ttl" in body:
        ttl = body["data_source_ttl"]
        if not isinstance(ttl, int) or isinstance(ttl, bool):
            raise BadRequest(
                "`data_source_ttl` must be a whole number of seconds."
            )
        try:
            validate_data_source_ttl(ttl)
        except ValidationError as e:
            raise BadRequest(
                f"`data_source_ttl`: {' '.join(e.messages)}"
            ) from e
        fields["data_source_ttl"] = ttl
    return fields


def _data_source_url(body):
    """``body``'s ``data_source_url``, checked with the web editor's own
    check; ``""`` if it sends none (or null, or ``""``)."""
    url = _text(body, "data_source_url", max_length=500, blank=True) or ""
    if not url:
        return ""
    try:
        validate_data_source_url(url)
    except ValidationError as e:
        raise BadRequest(f"`data_source_url`: {' '.join(e.messages)}") from e
    return url


def _update_page(request, page):
    """Apply a PATCH: a new title, the page's whole new source and/or its
    data source settings, based on ``base_revision`` and described by
    ``change_message``.
    ``page_detail`` has already checked the token with ``_write_denied``."""
    if not can_edit_page(request.user, page):
        return _error(403, "forbidden", "You can't edit this page.")
    try:
        body = _json_body(request)
        base_revision = body.get("base_revision")
        if not isinstance(base_revision, int) or isinstance(
            base_revision, bool
        ):
            raise BadRequest(
                "`base_revision` is required: the `revision` of the page "
                "you edited."
            )
        change_message = _text(
            body, "change_message", required=True, max_length=500
        )
        title = _text(body, "title", max_length=255)
        content = _text(body, "content", blank=True)
        data_source = _data_source(body)
        if title is None and content is None and not data_source:
            raise BadRequest(
                "Nothing to change: send `title`, `content`, "
                "`data_source_url` or `data_source_ttl`."
            )
        # Compared in the stored form: a tab that saving would expand back
        # to the same spaces is no change.
        if (
            title in (None, page.title)
            and (
                content is None
                or Page.normalize_content(content) == page.content
            )
            and all(getattr(page, f) == v for f, v in data_source.items())
        ):
            raise BadRequest(
                "Nothing to change: the page already has that title, "
                "content and data source."
            )
    except BadRequest as e:
        return _error(400, "invalid_request", str(e))

    # Any open editor blocks an API edit, the caller's own included: the
    # editor's form would otherwise save over this edit when it's submitted.
    lock = get_active_lock_for_page(page)
    if lock:
        return _error(
            409,
            "locked",
            "You have this page open in the wiki's editor; close it and try "
            "again."
            if lock.user_id == request.user.pk
            else "Someone is editing this page in the wiki; try again later.",
            locked_by=display_name(lock.user),
            locked_until=lock.expires_at,
        )

    old_directory, old_slug = page.directory, page.slug
    if title is not None:
        page.title = title
    if content is not None:
        page.content = content
    for field, value in data_source.items():
        setattr(page, field, value)
    page.change_message = change_message
    try:
        rev = save_page_edit(
            page,
            request.user,
            old_directory=old_directory,
            old_slug=old_slug,
            base_revision=base_revision,
        )
    except EditConflict as e:
        return _error(
            409,
            "conflict",
            "The page has changed since that revision; read it again.",
            revision=e.current_revision,
        )
    return _detail(page, request.user, rev.revision_number)


def _create_page(request):
    """Apply a POST: a new page in an existing directory, which it inherits
    its visibility and other settings from."""
    if denied := _write_denied(request):
        return denied
    try:
        body = _json_body(request)
        # Required, and never the top level, where a new page would start
        # out public rather than inheriting a directory's settings.
        directory_path = _text(body, "directory", required=True).strip("/")
        if not directory_path:
            raise BadRequest("`directory` must name a directory.")
        title = _text(body, "title", required=True, max_length=255)
        content = _text(body, "content", required=True, blank=True)
        change_message = _text(
            body, "change_message", required=True, max_length=500
        )
        data_source = _data_source(body)
    except BadRequest as e:
        return _error(400, "invalid_request", str(e))

    directory = Directory.objects.filter(path=directory_path).first()
    if directory is None or not can_view_directory(request.user, directory):
        return _error(404, "not_found", "There's no such directory.")
    if not can_edit_directory(request.user, directory):
        return _error(
            403, "forbidden", "You can't create pages in this directory."
        )

    page = Page(
        title=title,
        content=content,
        directory=directory,
        change_message=change_message,
        # As the web editor defaults a new page in a directory.
        visibility=Page.Visibility.INHERIT,
        editability=Page.Editability.INHERIT,
        in_sitemap=Page.SitemapStatus.INHERIT,
        in_llms_txt=Page.LlmsTxtStatus.INHERIT,
        **data_source,
    )
    rev = save_new_page(page, request.user)
    return _detail(page, request.user, rev.revision_number, status=201)
