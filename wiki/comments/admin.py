from django.contrib import admin

from .models import PageComment


@admin.register(PageComment)
class PageCommentAdmin(admin.ModelAdmin):
    list_display = [
        "page",
        "author",
        "status",
        "message",
        "created_at",
        "resolved_at",
    ]
    list_filter = ["status", "created_at", "resolved_at"]
    search_fields = [
        "page__title",
        "author__email",
        "author_email",
        "message",
    ]
    raw_id_fields = ["page", "author", "replied_by", "resolved_by"]
    date_hierarchy = "created_at"
    list_select_related = ["page", "author"]
