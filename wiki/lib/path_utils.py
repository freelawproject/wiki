"""Utilities for detecting path collisions between directories and pages."""

from django.utils.text import slugify

from wiki.directories.models import Directory


def page_path_conflicts_with_directory(slug, directory):
    """Check if a page's effective path would collide with an existing directory.

    Args:
        slug: The page's slug.
        directory: The Directory the page lives in (or None for root).

    Returns:
        True if a directory already exists at that path.
    """
    if directory and directory.path:
        full_path = f"{directory.path}/{slug}"
    else:
        full_path = slug
    return Directory.objects.filter(path=full_path).exists()


def directory_path_conflicts_with_page(dir_path):
    """Check if a directory path would collide with an existing page.

    A page's effective URL path is ``{directory.path}/{slug}``.  This
    function checks whether any page resolves to *dir_path*.

    Args:
        dir_path: The full directory path to check (e.g. "foo/bar").

    Returns:
        True if a page already occupies that path.
    """
    # Inline import to avoid circular dependency (pages/models → path_utils)
    from wiki.pages.models import Page

    slug = dir_path.rsplit("/", 1)[-1]
    parent_path = dir_path.rsplit("/", 1)[0] if "/" in dir_path else ""

    return Page.objects.filter(slug=slug, directory__path=parent_path).exists()


def compute_page_slug(title, directory=None, exclude_pk=None):
    """Generate a unique slug for a page within its directory.

    Slug uniqueness is scoped to ``directory``, so only siblings in the
    same directory can collide.

    Args:
        title: The page title to slugify.
        directory: The Directory the page lives in (or None for root).
        exclude_pk: PK to exclude from the uniqueness check (for updates).

    Returns:
        A slug string unique among pages in ``directory``.
    """
    # Inline import to avoid circular dependency (pages/models → path_utils)
    from wiki.pages.models import Page

    base_slug = slugify(title)
    new_slug = base_slug
    counter = 1
    while (
        Page.objects.filter(directory=directory, slug=new_slug)
        .exclude(pk=exclude_pk)
        .exists()
    ):
        counter += 1
        new_slug = f"{base_slug}-{counter}"
    return new_slug
