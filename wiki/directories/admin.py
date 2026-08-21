from django import forms
from django.contrib import admin
from django.db import transaction

from wiki.lib.page_utils import record_directory_move
from wiki.lib.path_utils import (
    MAX_DIRECTORY_DEPTH,
    directory_depth,
    directory_path_conflicts_with_page,
    update_descendant_paths,
)

from .models import Directory, DirectoryPermission, DirectoryRedirect


class DirectoryAdminForm(forms.ModelForm):
    """Applies the move view's path rules to a direct ``path`` edit.

    ``path`` is editable in the admin, and saving propagates it to every
    descendant, so the same rules ``_move_directory`` enforces have to hold
    here: a path a page already occupies is unreachable, and a path deep
    enough to push the subtree past the nesting cap breaks the ancestor-walking
    permission checks that cap exists to bound. Raising in the form turns both
    into a validation message instead of a relocated subtree or a 500 from the
    unique-path constraint on a descendant.
    """

    class Meta:
        model = Directory
        fields = "__all__"

    def clean_path(self):
        path = self.cleaned_data.get("path", "").strip("/")
        if directory_path_conflicts_with_page(path):
            raise forms.ValidationError("A page already occupies that path.")
        depth = directory_depth(path) + self._deepest_descendant_offset()
        if depth > MAX_DIRECTORY_DEPTH:
            raise forms.ValidationError(
                "That path would nest this directory, or its contents, more "
                f"than {MAX_DIRECTORY_DEPTH} levels deep."
            )
        return path

    def _deepest_descendant_offset(self):
        """How many levels below this directory its deepest descendant sits.

        Read from the stored path: field cleaning runs before the instance is
        updated with the submitted values, but the subtree is defined by where
        the directory is now, not where it's headed.
        """
        if not self.instance.pk:
            return 0
        old_path = (
            Directory.objects.filter(pk=self.instance.pk)
            .values_list("path", flat=True)
            .first()
        )
        if not old_path:
            return 0
        descendant_paths = Directory.objects.filter(
            path__startswith=f"{old_path}/"
        ).values_list("path", flat=True)
        return max(
            (
                directory_depth(p) - directory_depth(old_path)
                for p in descendant_paths
            ),
            default=0,
        )


class DirectoryPermissionInline(admin.TabularInline):
    model = DirectoryPermission
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Directory)
class DirectoryAdmin(admin.ModelAdmin):
    form = DirectoryAdminForm
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
