from django.contrib import admin

from .models import (
    DirectorySubscription,
    PageSubscription,
)


@admin.register(PageSubscription)
class PageSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "page", "status", "subscribed_at"]
    list_filter = ["status", "subscribed_at"]
    search_fields = ["user__email", "page__title", "page__slug"]
    raw_id_fields = ["user", "page"]
    readonly_fields = ["subscribed_at"]
    list_select_related = ["user", "page"]
    date_hierarchy = "subscribed_at"


@admin.register(DirectorySubscription)
class DirectorySubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "directory", "status", "subscribed_at"]
    list_filter = ["status", "subscribed_at"]
    search_fields = ["user__email", "directory__title", "directory__path"]
    raw_id_fields = ["user", "directory"]
    readonly_fields = ["subscribed_at"]
    list_select_related = ["user", "directory"]
    date_hierarchy = "subscribed_at"
