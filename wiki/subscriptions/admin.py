from django.contrib import admin

from .models import PageSubscription


@admin.register(PageSubscription)
class PageSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "page", "subscribed_at"]
    list_filter = ["subscribed_at"]
    search_fields = ["user__email", "page__title", "page__slug"]
    raw_id_fields = ["user", "page"]
    readonly_fields = ["subscribed_at"]
    list_select_related = ["user", "page"]
    date_hierarchy = "subscribed_at"
