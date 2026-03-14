from django.urls import path

from wiki.subscriptions.views import toggle_subscription

from . import views

urlpatterns = [
    path(
        "<path:path>/permissions/",
        views.page_permissions,
        name="page_permissions",
    ),
    path("<path:path>/edit/", views.page_edit, name="page_edit"),
    path("<path:path>/move/", views.page_move, name="page_move"),
    path("<path:path>/delete/", views.page_delete, name="page_delete"),
    path("<path:path>/history/", views.page_history, name="page_history"),
    path(
        "<path:path>/backlinks/",
        views.page_backlinks,
        name="page_backlinks",
    ),
    path(
        "<path:path>/diff/<int:v1>/<int:v2>/",
        views.page_diff,
        name="page_diff",
    ),
    path(
        "<path:path>/revert/<int:rev_num>/",
        views.page_revert,
        name="page_revert",
    ),
    path(
        "<path:path>/subscribe/",
        toggle_subscription,
        name="page_subscribe",
    ),
    path("<path:path>/pin/", views.toggle_pin, name="page_toggle_pin"),
    # Raw markdown — must be before the catch-all
    path(
        "<path:path>.md",
        views.page_raw_markdown,
        name="page_raw_markdown",
    ),
    # Unified catch-all — checks directory first, then page
    path("<path:path>", views.resolve_path, name="resolve_path"),
]
