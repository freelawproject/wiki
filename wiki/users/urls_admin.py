from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.admin_list, name="admin_list"),
    path(
        "<int:pk>/toggle/",
        views.admin_toggle,
        name="admin_toggle",
    ),
    path(
        "<int:pk>/archive/",
        views.admin_archive_toggle,
        name="admin_archive_toggle",
    ),
    path("groups/", include("wiki.groups.urls")),
]
