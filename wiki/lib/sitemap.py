"""Django sitemaps for public pages and directories."""

from django.contrib.sitemaps import Sitemap
from django.db.models import Q

from wiki.directories.models import Directory
from wiki.pages.models import Page


def _public_directory_ids():
    """Return IDs of directories where the entire ancestor chain is public.

    A directory is truly public only when it *and every ancestor* has
    visibility=PUBLIC.  A public child inside an internal parent is
    inaccessible to anonymous visitors and must not appear in the
    sitemap.
    """
    public = Directory.Visibility.PUBLIC
    public_ids = set()
    non_public_ids = set()

    for directory in Directory.objects.only(
        "pk", "parent_id", "visibility"
    ).iterator():
        if directory.visibility != public:
            non_public_ids.add(directory.pk)
        else:
            public_ids.add(directory.pk)

    # Build parent lookup
    parent_map = dict(
        Directory.objects.values_list("pk", "parent_id").iterator()
    )

    # Walk each public directory's ancestor chain; reject if any
    # ancestor is non-public.
    truly_public = set()
    for dir_id in public_ids:
        chain_ok = True
        current = dir_id
        while current is not None:
            if current in non_public_ids:
                chain_ok = False
                break
            if current in truly_public:
                break
            current = parent_map.get(current)
        if chain_ok:
            truly_public.add(dir_id)

    return truly_public


class PageSitemap(Sitemap):
    """Sitemap for all publicly visible wiki pages.

    Only includes pages that are themselves public AND reside in a
    fully-public directory chain (or at the root level with no
    directory).
    """

    changefreq = "weekly"
    priority = 0.7

    def items(self):
        public_dir_ids = _public_directory_ids()
        return (
            Page.objects.filter(visibility=Page.Visibility.PUBLIC)
            .filter(
                Q(directory__isnull=True) | Q(directory_id__in=public_dir_ids)
            )
            .order_by("pk")
        )

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class DirectorySitemap(Sitemap):
    """Sitemap for all publicly visible directories (including root).

    Only includes directories whose entire ancestor chain is public.
    """

    changefreq = "weekly"
    priority = 0.5

    def items(self):
        public_dir_ids = _public_directory_ids()
        return Directory.objects.filter(pk__in=public_dir_ids).order_by("pk")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()
