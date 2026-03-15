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


def _sitemap_directory_ids():
    """Return IDs of directories eligible for the sitemap.

    A directory is eligible when it AND every ancestor is public AND
    has in_sitemap=True.  If any ancestor has in_sitemap=False the
    entire subtree is excluded.
    """
    public = Directory.Visibility.PUBLIC
    eligible_ids = set()
    ineligible_ids = set()

    for directory in Directory.objects.only(
        "pk", "parent_id", "visibility", "in_sitemap", "path"
    ).iterator():
        # Root directory always participates in sitemap (can't be excluded)
        is_root = directory.path == ""
        if directory.visibility != public or (
            not directory.in_sitemap and not is_root
        ):
            ineligible_ids.add(directory.pk)
        else:
            eligible_ids.add(directory.pk)

    parent_map = dict(
        Directory.objects.values_list("pk", "parent_id").iterator()
    )

    truly_eligible = set()
    for dir_id in eligible_ids:
        chain_ok = True
        current = dir_id
        while current is not None:
            if current in ineligible_ids:
                chain_ok = False
                break
            if current in truly_eligible:
                break
            current = parent_map.get(current)
        if chain_ok:
            truly_eligible.add(dir_id)

    return truly_eligible


def _llms_directory_map():
    """Return a dict mapping directory ID to its effective llms.txt status.

    Only directories that are public through the entire ancestor chain
    are included.  The effective status is the most restrictive value
    in the chain: exclude > optional > include.
    """
    public = Directory.Visibility.PUBLIC
    # Restrictiveness ranking: exclude > optional > include
    _rank = {"exclude": 2, "optional": 1, "include": 0}

    dir_data = {}  # pk -> (parent_id, visibility, in_llms_txt, path)
    for d in Directory.objects.only(
        "pk", "parent_id", "visibility", "in_llms_txt", "path"
    ).iterator():
        dir_data[d.pk] = (d.parent_id, d.visibility, d.in_llms_txt, d.path)

    result = {}  # pk -> effective status
    for dir_id, (parent_id, visibility, status, path) in dir_data.items():
        if visibility != public:
            continue

        # Root directory always treated as "include" (can't be excluded)
        effective = "include" if path == "" else status
        chain_ok = True
        current = parent_id
        while current is not None:
            data = dir_data.get(current)
            if data is None:
                break
            ancestor_parent, ancestor_vis, ancestor_status, ancestor_path = (
                data
            )
            if ancestor_vis != public:
                chain_ok = False
                break
            # Root always treated as "include"
            if ancestor_path != "":
                if _rank.get(ancestor_status, 2) > _rank.get(effective, 0):
                    effective = ancestor_status
            current = ancestor_parent

        if chain_ok:
            result[dir_id] = effective

    return result


class PageSitemap(Sitemap):
    """Sitemap for all publicly visible wiki pages.

    Only includes pages that are themselves public AND reside in a
    fully-public directory chain (or at the root level with no
    directory), AND have in_sitemap=True with all ancestor directories
    also having in_sitemap=True.
    """

    changefreq = "weekly"
    priority = 0.7

    def items(self):
        eligible_dir_ids = _sitemap_directory_ids()
        return (
            Page.objects.filter(
                visibility=Page.Visibility.PUBLIC,
                in_sitemap=True,
            )
            .filter(
                Q(directory__isnull=True)
                | Q(directory_id__in=eligible_dir_ids)
            )
            .order_by("pk")
        )

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class DirectorySitemap(Sitemap):
    """Sitemap for all publicly visible directories (including root).

    Only includes directories whose entire ancestor chain is public
    and has in_sitemap=True.
    """

    changefreq = "weekly"
    priority = 0.5

    def items(self):
        eligible_dir_ids = _sitemap_directory_ids()
        return Directory.objects.filter(pk__in=eligible_dir_ids).order_by("pk")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()
