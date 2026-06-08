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
    path("access/", views.access_list, name="access_list"),
    path(
        "access/domains/add/",
        views.access_add_domain,
        name="access_add_domain",
    ),
    path(
        "access/domains/<int:pk>/delete/",
        views.access_delete_domain,
        name="access_delete_domain",
    ),
    path(
        "access/emails/add/", views.access_add_email, name="access_add_email"
    ),
    path(
        "access/emails/<int:pk>/delete/",
        views.access_delete_email,
        name="access_delete_email",
    ),
    path("groups/", include("wiki.groups.urls")),
]
