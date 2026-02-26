"""Django sitemaps for public pages and directories."""

from django.contrib.sitemaps import Sitemap

from wiki.directories.models import Directory
from wiki.pages.models import Page


class PageSitemap(Sitemap):
    """Sitemap for all publicly visible wiki pages."""

    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Page.objects.filter(visibility=Page.Visibility.PUBLIC).order_by(
            "pk"
        )

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class DirectorySitemap(Sitemap):
    """Sitemap for all publicly visible directories (including root)."""

    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return Directory.objects.filter(
            visibility=Directory.Visibility.PUBLIC
        ).order_by("pk")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()
