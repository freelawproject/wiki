from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import SystemConfig, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    readonly_fields = ["magic_link_token", "magic_link_expires", "created_at"]
    fieldsets = (
        (
            None,
            {"fields": ("display_name", "gravatar_url")},
        ),
        (
            "Auth tokens",
            {
                "fields": (
                    "magic_link_token",
                    "magic_link_expires",
                    "created_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )


# Unregister the default User admin and re-register with our inline
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = [
        "email",
        "get_display_name",
        "is_staff",
        "is_superuser",
        "is_active",
        "date_joined",
    ]
    list_filter = ["is_staff", "is_superuser", "is_active", "date_joined"]
    search_fields = ["email", "username", "profile__display_name"]

    @admin.display(description="Display name")
    def get_display_name(self, obj):
        try:
            return obj.profile.display_name or "—"
        except UserProfile.DoesNotExist:
            return "—"

    def save_model(self, request, obj, form, change):
        # SECURITY: enforce @free.law domain restriction in admin too.
        # The login form validates this, but admin bypasses that form.
        if obj.email and not obj.email.endswith("@free.law"):
            messages.error(
                request,
                "Only @free.law email addresses are allowed.",
            )
            return
        super().save_model(request, obj, form, change)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "display_name", "created_at"]
    search_fields = ["user__email", "display_name"]
    raw_id_fields = ["user"]
    readonly_fields = [
        "magic_link_token",
        "magic_link_expires",
        "gravatar_url",
        "created_at",
    ]
    list_select_related = ["user"]


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ["__str__", "owner"]
    raw_id_fields = ["owner"]

    def has_add_permission(self, request):
        # Only one SystemConfig row should exist (pk=1)
        return not SystemConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
