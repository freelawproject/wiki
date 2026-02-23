from django.contrib import admin

from .models import Directory, DirectoryPermission


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


@admin.register(DirectoryPermission)
class DirectoryPermissionAdmin(admin.ModelAdmin):
    list_display = [
        "directory",
        "user",
        "group",
        "permission_type",
    ]
    list_filter = ["permission_type"]
    search_fields = [
        "directory__title",
        "directory__path",
        "user__email",
        "group__name",
    ]
    raw_id_fields = ["directory", "user"]
    list_select_related = ["directory", "user", "group"]
