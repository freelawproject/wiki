from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from wiki.lib.access import is_email_allowed
from wiki.lib.permissions import (
    is_system_owner,
    mark_domain_grants_dormant,
    reactivate_domain_grants,
)
from wiki.lib.sessions import revoke_disallowed

from .models import AllowedDomain, AllowedEmail, SystemConfig, UserProfile
from .tasks import notify_access_change


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
        # SECURITY: enforce the email allowlist in admin too. The login form
        # validates this, but admin bypasses that form. Block a blank email
        # as well — don't let the check be skipped by leaving it empty.
        if not is_email_allowed(obj.email):
            messages.error(
                request,
                "This user needs a non-empty email address that's on the "
                "allowlist. Add its domain or the address under Allowed "
                "domains / Allowed emails first.",
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


class AccessRuleAdmin(admin.ModelAdmin):
    """Base admin for allowlist models.

    Mirrors the custom Access UI: every add/edit/delete (including bulk
    deletes) emails the owner and managers, so the Django admin path leaves
    the same audit trail as ``/u/admins/access/``.
    """

    audit_item_type = ""  # "domain" / "email address"
    audit_value_field = ""  # model field holding the human-readable value

    def _audit_value(self, obj):
        return getattr(obj, self.audit_value_field)

    def _affected_users(self, value):
        """Users whose sign-in depends on this rule value. Subclass hook."""
        raise NotImplementedError

    def _revoke(self, value):
        """End sessions + magic links for users this value no longer allows."""
        revoke_disallowed(self._affected_users(value))

    def _on_added(self, value):
        """Hook: rule value was added/restored. Subclass override (no-op)."""

    def _on_removed(self, value):
        """Hook: rule value was removed. Subclass override (no-op)."""

    def save_model(self, request, obj, form, change):
        old_value = None
        if change:
            previous = type(obj).objects.filter(pk=obj.pk).first()
            old_value = self._audit_value(previous) if previous else None
        super().save_model(request, obj, form, change)
        new_value = self._audit_value(obj)
        notify_access_change(
            request.user,
            "updated" if change else "added",
            self.audit_item_type,
            new_value,
        )
        self._on_added(new_value)
        # A rename strands users on the old value; revoke them if now barred.
        if old_value and old_value != new_value:
            self._revoke(old_value)
            self._on_removed(old_value)

    def delete_model(self, request, obj):
        value = self._audit_value(obj)
        super().delete_model(request, obj)
        notify_access_change(
            request.user, "removed", self.audit_item_type, value
        )
        self._revoke(value)
        self._on_removed(value)

    def delete_queryset(self, request, queryset):
        values = [self._audit_value(o) for o in queryset]
        super().delete_queryset(request, queryset)
        for value in values:
            notify_access_change(
                request.user, "removed", self.audit_item_type, value
            )
            self._revoke(value)
            self._on_removed(value)


@admin.register(AllowedDomain)
class AllowedDomainAdmin(AccessRuleAdmin):
    list_display = ["domain", "tier", "note", "created_at"]
    list_filter = ["tier"]
    search_fields = ["domain", "note"]
    audit_item_type = "domain"
    audit_value_field = "domain"

    def _affected_users(self, value):
        return User.objects.filter(email__iendswith=f"@{value}")

    # Mirror the custom Access views: retain a domain's content grants but
    # mark them dormant on removal and reactivate them on re-add.
    def _on_added(self, value):
        reactivate_domain_grants(value)

    def _on_removed(self, value):
        mark_domain_grants_dormant(value)

    # SECURITY: domains are owner-only, matching the custom Access views.
    # Managers are Django superusers (admin_toggle sets is_superuser), so
    # permission checks would otherwise short-circuit to True for them.
    def has_add_permission(self, request):
        return is_system_owner(request.user)

    def has_change_permission(self, request, obj=None):
        return is_system_owner(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_system_owner(request.user)


@admin.register(AllowedEmail)
class AllowedEmailAdmin(AccessRuleAdmin):
    list_display = ["email", "tier", "note", "created_at"]
    list_filter = ["tier"]
    search_fields = ["email", "note"]
    audit_item_type = "email address"
    audit_value_field = "email"

    def _affected_users(self, value):
        return User.objects.filter(email__iexact=value)
