from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import RedirectView

from wiki.lib.sitemap import DirectorySitemap, PageSitemap
from wiki.lib.views import robots_txt
from wiki.users.views import logout_view

sitemaps = {
    "pages": PageSitemap,
    "directories": DirectorySitemap,
}

urlpatterns = [
    path("", RedirectView.as_view(url="/c/", permanent=False)),
    path("robots.txt", robots_txt, name="robots_txt"),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("u/login/", include("wiki.users.urls")),
    path("u/logout/", logout_view, name="logout"),
    path("u/settings/", include("wiki.users.urls_settings")),
    path("u/admins/", include("wiki.users.urls_admin")),
    path("search/", include("wiki.pages.urls_search")),
    path("api/", include("wiki.pages.urls_api")),
    path("files/", include("wiki.pages.urls_files")),
    path("unsubscribe/", include("wiki.subscriptions.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEVELOPMENT:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
        path(
            "__reload__/",
            include("django_browser_reload.urls"),
        ),
    ]

# Content catch-all — must be last
urlpatterns += [
    path("c/", include("wiki.proposals.urls")),
    path("c/", include("wiki.directories.urls")),
    path("c/", include("wiki.pages.urls")),
]
