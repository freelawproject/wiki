from django.contrib import admin

from .models import (
    FileUpload,
    Page,
    PagePermission,
    PageRevision,
    PageViewTally,
    SlugRedirect,
)


class PageRevisionInline(admin.TabularInline):
    model = PageRevision
    extra = 0
    fields = [
        "revision_number",
        "change_message",
        "created_by",
        "created_at",
    ]
    readonly_fields = ["revision_number", "created_by", "created_at"]
    ordering = ["-revision_number"]
    show_change_link = True


class PagePermissionInline(admin.TabularInline):
    model = PagePermission
    extra = 0
    raw_id_fields = ["user"]


class SlugRedirectInline(admin.TabularInline):
    model = SlugRedirect
    extra = 0
    readonly_fields = ["old_slug"]


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "slug",
        "directory",
        "visibility",
        "editability",
        "owner",
        "is_pinned",
        "is_deleted",
        "view_count",
        "updated_at",
    ]
    list_filter = [
        "is_pinned",
        "is_deleted",
        "visibility",
        "editability",
        "directory",
        "created_at",
        "updated_at",
    ]
    search_fields = ["title", "slug", "content"]
    raw_id_fields = [
        "owner",
        "created_by",
        "updated_by",
        "deleted_by",
        "directory",
    ]
    readonly_fields = [
        "view_count",
        "search_vector",
        "created_at",
        "updated_at",
        "deleted_at",
    ]
    prepopulated_fields = {"slug": ("title",)}
    list_select_related = ["directory", "owner"]
    date_hierarchy = "created_at"
    actions = ["restore_pages"]
    inlines = [
        PagePermissionInline,
        SlugRedirectInline,
        PageRevisionInline,
    ]
    fieldsets = (
        (None, {"fields": ("title", "slug", "content", "directory")}),
        (
            "Ownership & Visibility",
            {
                "fields": (
                    "owner",
                    "visibility",
                    "editability",
                    "change_message",
                )
            },
        ),
        (
            "Deletion",
            {
                "fields": (
                    "is_deleted",
                    "deleted_at",
                    "deleted_by",
                ),
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "view_count",
                    "created_by",
                    "updated_by",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Show all pages (including deleted) in admin."""
        return Page.all_objects.all()

    @admin.action(description="Restore selected pages")
    def restore_pages(self, request, queryset):
        count = queryset.filter(is_deleted=True).update(
            is_deleted=False, deleted_at=None, deleted_by=None
        )
        self.message_user(request, f"Restored {count} page(s).")


@admin.register(PageRevision)
class PageRevisionAdmin(admin.ModelAdmin):
    list_display = [
        "page",
        "revision_number",
        "change_message",
        "created_by",
        "created_at",
    ]
    list_filter = ["created_at"]
    search_fields = [
        "page__title",
        "change_message",
        "created_by__email",
    ]
    raw_id_fields = ["page", "created_by"]
    readonly_fields = ["created_at"]
    list_select_related = ["page", "created_by"]


@admin.register(PagePermission)
class PagePermissionAdmin(admin.ModelAdmin):
    list_display = ["page", "user", "group", "permission_type"]
    list_filter = ["permission_type"]
    search_fields = [
        "page__title",
        "user__email",
        "group__name",
    ]
    raw_id_fields = ["page", "user"]
    list_select_related = ["page", "user", "group"]


@admin.register(FileUpload)
class FileUploadAdmin(admin.ModelAdmin):
    list_display = [
        "original_filename",
        "page",
        "uploaded_by",
        "content_type",
        "created_at",
    ]
    list_filter = ["content_type", "created_at"]
    search_fields = [
        "original_filename",
        "page__title",
        "uploaded_by__email",
    ]
    raw_id_fields = ["page", "uploaded_by"]
    readonly_fields = ["created_at"]
    list_select_related = ["page", "uploaded_by"]


@admin.register(SlugRedirect)
class SlugRedirectAdmin(admin.ModelAdmin):
    list_display = ["old_slug", "page"]
    search_fields = ["old_slug", "page__title", "page__slug"]
    raw_id_fields = ["page"]
    list_select_related = ["page"]


@admin.register(PageViewTally)
class PageViewTallyAdmin(admin.ModelAdmin):
    list_display = ["page", "count", "created_at"]
    raw_id_fields = ["page"]
    readonly_fields = ["page", "count", "created_at"]
    list_select_related = ["page"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
