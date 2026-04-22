"""Shared page-related utilities."""

from django.db.models import Q
from django.http import Http404

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
