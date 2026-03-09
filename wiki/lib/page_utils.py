"""Shared page-related utilities."""

from django.shortcuts import get_object_or_404

from wiki.pages.models import Page


def get_page_from_path(path):
    """Resolve a content path to a Page object."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    return get_object_or_404(Page, slug=slug)
