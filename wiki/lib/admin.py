from django.contrib import admin

from wiki.lib.models import EditLock


@admin.register(EditLock)
class EditLockAdmin(admin.ModelAdmin):
    list_display = ("user", "page", "directory", "created_at", "expires_at")
    list_filter = ("created_at",)
    raw_id_fields = ("user", "page", "directory")
