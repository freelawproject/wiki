from django.contrib import admin
from django.db import transaction

from wiki.lib.page_utils import record_directory_move
from wiki.lib.path_utils import update_descendant_paths

from .models import Directory, DirectoryPermission, DirectoryRedirect


class DirectoryPermissionInline(admin.TabularInline):
    model = DirectoryPermission
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Directory)
class DirectoryAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "path",
        "parent",
        "owner",
        "visibility",
        "editability",
        "created_at",
        "updated_at",
    ]
    list_filter = ["visibility", "editability", "created_at"]
    search_fields = ["title", "path"]
    raw_id_fields = ["parent", "owner", "created_by"]
    readonly_fields = ["created_at", "updated_at"]
    list_select_related = ["parent", "owner"]
    inlines = [DirectoryPermissionInline]
    fieldsets = (
        (None, {"fields": ("title", "path", "description", "parent")}),
        (
            "Ownership & Settings",
            {"fields": ("owner", "visibility", "editability", "created_by")},
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        """Save the directory, keeping the subtree and old URLs intact.

        ``path`` and ``parent`` are both editable here, so an admin save can
        move a directory just like the move view does. Rewriting the path
        changes the URL of every page beneath it, so the descendants have to
        follow and the old paths need redirects.
        """
        old_path = None
        if change and obj.pk:
            old_path = (
                Directory.objects.filter(pk=obj.pk)
                .values_list("path", flat=True)
                .first()
            )

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if old_path is None or old_path == obj.path:
                return
            old_subtree_paths = [(obj.pk, old_path)] + list(
                Directory.objects.filter(
                    path__startswith=f"{old_path}/"
                ).values_list("pk", "path")
            )
            update_descendant_paths(obj)
            record_directory_move(old_subtree_paths)


@admin.register(DirectoryPermission)
class DirectoryPermissionAdmin(admin.ModelAdmin):
    list_display = [
        "directory",
        "user",
        "group",
        "grant_domain",
        "permission_type",
    ]
    list_filter = ["permission_type"]
    search_fields = [
        "directory__title",
        "directory__path",
        "user__email",
        "group__name",
        "grant_domain",
    ]
    raw_id_fields = ["directory", "user"]
    list_select_related = ["directory", "user", "group"]


@admin.register(DirectoryRedirect)
class DirectoryRedirectAdmin(admin.ModelAdmin):
    list_display = ["old_path", "directory"]
    search_fields = ["old_path", "directory__path"]
    raw_id_fields = ["directory"]
    list_select_related = ["directory"]
