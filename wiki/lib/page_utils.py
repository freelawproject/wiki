"""Shared page-related utilities."""

from django.db.models import Q
from django.http import Http404

from wiki.directories.models import Directory, DirectoryRedirect
from wiki.pages.models import Page, SlugRedirect


def split_content_path(clean_path):
    """Split a /c/ content path into (directory_path, slug).

    Root-level paths like "overview" return ("", "overview").
    Nested paths like "hr/overview" return ("hr", "overview").
    """
    clean_path = clean_path.strip("/")
    if "/" in clean_path:
        dir_path, slug = clean_path.rsplit("/", 1)
    else:
        dir_path, slug = "", clean_path
    return dir_path, slug


def _root_directory_q(field_name):
    """Q that matches either directory=None or directory with path=''.

    Root-level pages/redirects can legitimately have either form.
    """
    return Q(**{f"{field_name}__isnull": True}) | Q(
        **{f"{field_name}__path": ""}
    )


def page_at_path(path):
    """Look up a Page by literal (directory_path, slug).

    Returns None if the directory component doesn't resolve or no page
    with that slug exists directly under that directory.
    """
    dir_path, slug = split_content_path(path)
    qs = Page.objects.filter(slug=slug).select_related("directory", "owner")
    if dir_path:
        qs = qs.filter(directory__path=dir_path)
    else:
        qs = qs.filter(_root_directory_q("directory"))
    return qs.first()


def slug_redirect_at_path(path):
    """Find a SlugRedirect matching (directory_path, old_slug)."""
    dir_path, slug = split_content_path(path)
    qs = SlugRedirect.objects.filter(old_slug=slug).select_related("page")
    if dir_path:
        qs = qs.filter(directory__path=dir_path)
    else:
        qs = qs.filter(_root_directory_q("directory"))
    return qs.first()


def get_page_from_path(path):
    """Resolve a content path to a Page or raise Http404.

    Under directory-scoped slugs, looking up by bare slug alone is
    ambiguous; the full (directory, slug) path is authoritative.
    """
    page = page_at_path(path)
    if page is None:
        raise Http404
    return page


def record_page_move(page, old_directory, old_slug):
    """Leave a redirect behind when a page's (directory, slug) has changed.

    Page URLs are ``(directory path, slug)``, and the slug follows the title,
    so a rename, a move to another directory, or a title revert all change the
    URL. Every code path that relocates a page must call this — otherwise the
    old URL 404s and every link to it, inside the wiki and out, breaks.

    ``old_directory`` and ``old_slug`` are the values snapshotted *before* the
    save. No-ops when the page didn't actually move.
    """
    old_directory_id = old_directory.pk if old_directory else None
    if old_directory_id == page.directory_id and old_slug == page.slug:
        return None

    # A redirect sitting at the page's *new* location can never fire — the
    # literal page match wins first — and it holds the unique (directory,
    # old_slug) slot, so clear it before recording the move.
    SlugRedirect.objects.filter(
        directory=page.directory, old_slug=page.slug
    ).delete()

    redirect_obj, _ = SlugRedirect.objects.update_or_create(
        directory=old_directory,
        old_slug=old_slug,
        defaults={"page": page},
    )
    return redirect_obj


def record_directory_move(old_paths):
    """Leave a redirect behind for every directory a move relocated.

    ``old_paths`` is a list of ``(pk, old_path)`` tuples snapshotted before
    the move — the directory itself plus every descendant, since moving a
    directory rewrites the whole subtree's paths and therefore the URL of
    every page under it.
    """
    moved = Directory.objects.in_bulk([pk for pk, _ in old_paths])
    relocated = [
        (moved[pk], old_path)
        for pk, old_path in old_paths
        if pk in moved and moved[pk].path != old_path
    ]
    if not relocated:
        return

    # Stale rows standing where a real directory now lives can never fire, and
    # they hold the unique old_path slot. Clear them all before recording, so
    # that a path freed by this move is available to it.
    DirectoryRedirect.objects.filter(
        old_path__in=[d.path for d, _ in relocated]
    ).delete()
    for directory, old_path in relocated:
        DirectoryRedirect.objects.update_or_create(
            old_path=old_path, defaults={"directory": directory}
        )


def directory_at_old_path(dir_path):
    """Resolve a directory path left behind by a move, or None."""
    if not dir_path:
        return None
    redirect_obj = (
        DirectoryRedirect.objects.filter(old_path=dir_path)
        .select_related("directory")
        .first()
    )
    return redirect_obj.directory if redirect_obj else None


def moved_target_url(path):
    """Resolve ``path`` through directory-move history, or return None.

    Covers a request for a moved directory's own old URL, and for a page whose
    URL only changed because one of its ancestor directories moved. Redirects
    point at directories/pages by FK, so a chain of moves never needs
    following — each hop resolves straight to the current location.
    """
    clean_path = path.strip("/")

    directory = directory_at_old_path(clean_path)
    if directory is not None:
        return directory.get_absolute_url()

    dir_path, slug = split_content_path(clean_path)
    directory = directory_at_old_path(dir_path)
    if directory is None:
        return None

    page = Page.objects.filter(directory=directory, slug=slug).first()
    if page is not None:
        return page.get_absolute_url()

    # The page may have been renamed as well as carried along by the move.
    redirect_obj = (
        SlugRedirect.objects.filter(directory=directory, old_slug=slug)
        .select_related("page")
        .first()
    )
    return redirect_obj.page.get_absolute_url() if redirect_obj else None
