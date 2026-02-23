from django.urls import path

from wiki.directories import views as dir_views
from wiki.users import views as user_views

from . import views

urlpatterns = [
    path("preview/", views.page_preview_htmx, name="page_preview"),
    path("upload/", views.file_upload_htmx, name="file_upload"),
    path("page-search/", views.page_search_htmx, name="page_search"),
    path(
        "dir-search/",
        dir_views.directory_search_htmx,
        name="dir_search",
    ),
    path(
        "user-search/",
        user_views.user_search_htmx,
        name="user_search",
    ),
    path(
        "check-page-perms/",
        views.check_page_permissions,
        name="check_page_perms",
    ),
    # Keep old URL as alias
    path(
        "check-mention-perms/",
        views.check_mention_permissions,
        name="check_mention_perms",
    ),
]
