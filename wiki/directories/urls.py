from django.urls import path

from wiki.pages.views import page_create

from . import views

urlpatterns = [
    path("", views.root_view, name="root"),
    path("new/", page_create, name="page_create"),
    path("new-dir/", views.directory_create, name="directory_create"),
    path("edit-dir/", views.directory_edit_root, name="directory_edit_root"),
    path(
        "permissions-dir/",
        views.directory_permissions_root,
        name="directory_permissions_root",
    ),
    path(
        "apply-permissions-dir/",
        views.directory_apply_permissions_root,
        name="directory_apply_permissions_root",
    ),
    path(
        "history-dir/",
        views.directory_history_root,
        name="directory_history_root",
    ),
    path(
        "diff-dir/<int:v1>/<int:v2>/",
        views.directory_diff_root,
        name="directory_diff_root",
    ),
    path(
        "revert-dir/<int:rev_num>/",
        views.directory_revert_root,
        name="directory_revert_root",
    ),
    path(
        "<path:path>/new/",
        views.page_create_in_directory,
        name="page_create_in_dir",
    ),
    path(
        "<path:path>/new-dir/",
        views.directory_create,
        name="directory_create_in_dir",
    ),
    path(
        "<path:path>/edit-dir/",
        views.directory_edit,
        name="directory_edit",
    ),
    path(
        "<path:path>/permissions-dir/",
        views.directory_permissions,
        name="directory_permissions",
    ),
    path(
        "<path:path>/move-dir/",
        views.directory_move,
        name="directory_move",
    ),
    path(
        "<path:path>/delete-dir/",
        views.directory_delete,
        name="directory_delete",
    ),
    path(
        "<path:path>/apply-permissions-dir/",
        views.directory_apply_permissions,
        name="directory_apply_permissions",
    ),
    path(
        "<path:path>/history-dir/",
        views.directory_history,
        name="directory_history",
    ),
    path(
        "<path:path>/diff-dir/<int:v1>/<int:v2>/",
        views.directory_diff,
        name="directory_diff",
    ),
    path(
        "<path:path>/revert-dir/<int:rev_num>/",
        views.directory_revert,
        name="directory_revert",
    ),
]
