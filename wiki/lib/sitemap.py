"""Django sitemaps for public pages and directories.

Uses the inheritance resolution system — each item's effective value is
either explicit (takes effect directly) or inherited (resolved from the
nearest ancestor with an explicit value).
"""

from django.contrib.sitemaps import Sitemap
from django.db.models import Q

from wiki.directories.models import Directory
from wiki.lib.inheritance import resolve_all_directory_settings
from wiki.pages.models import Page


def _effectively_public_directory_ids():
    """Return IDs of directories whose effective visibility is public."""
    resolved = resolve_all_directory_settings("visibility")
    return {
        dir_id
        for dir_id, (eff_value, _, _) in resolved.items()
        if eff_value == "public"
    }


def _sitemap_directory_ids():
    """Return IDs of directories eligible for the sitemap.

    A directory is eligible when its effective visibility is public AND
    its effective in_sitemap is "include".
    """
    vis_resolved = resolve_all_directory_settings("visibility")
    sitemap_resolved = resolve_all_directory_settings("in_sitemap")

    return {
        dir_id
        for dir_id in vis_resolved
        if vis_resolved[dir_id][0] == "public"
        and sitemap_resolved.get(dir_id, ("exclude", None, None))[0]
        == "include"
    }


def _llms_directory_map():
    """Return a dict mapping directory ID to its effective llms.txt status.

    Only includes directories whose effective visibility is public.
    """
    vis_resolved = resolve_all_directory_settings("visibility")
    llms_resolved = resolve_all_directory_settings("in_llms_txt")

    return {
        dir_id: llms_resolved.get(dir_id, ("exclude", None, None))[0]
        for dir_id in vis_resolved
        if vis_resolved[dir_id][0] == "public"
    }


def _page_sitemap_q():
    """Return a Q filter for pages that should appear in the sitemap.

    Pages must be effectively public AND effectively in the sitemap.
    Handles both explicit values and inherited values.
    """
    eligible_dir_ids = _sitemap_directory_ids()
    public_dir_ids = _effectively_public_directory_ids()

    # Pages that are effectively public
    effectively_public = Q(visibility="public") | Q(
        visibility="inherit", directory_id__in=public_dir_ids
    )

    # Pages that are effectively in the sitemap
    effectively_in_sitemap = Q(in_sitemap="include") | Q(
        in_sitemap="inherit", directory_id__in=eligible_dir_ids
    )

    # Root-level pages (no directory): only explicit values apply
    root_pages = Q(
        directory__isnull=True, visibility="public", in_sitemap="include"
    )

    return (
        effectively_public
        & effectively_in_sitemap
        & Q(directory__isnull=False)
    ) | root_pages


class PageSitemap(Sitemap):
    """Sitemap for all effectively public wiki pages with sitemap included."""

    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Page.objects.filter(_page_sitemap_q()).order_by("pk")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class DirectorySitemap(Sitemap):
    """Sitemap for all effectively public directories with sitemap included."""

    changefreq = "weekly"
    priority = 0.5

    def items(self):
        eligible_dir_ids = _sitemap_directory_ids()
        return Directory.objects.filter(pk__in=eligible_dir_ids).order_by("pk")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()
