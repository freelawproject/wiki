from django.conf import settings
from django.db import models
from django.urls import reverse


class Directory(models.Model):
    """A directory in the wiki hierarchy.

    Directories organize pages into a tree structure. The root
    directory has parent=None and path="".
    """

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        INTERNAL = "internal", "FLP Staff"
        PRIVATE = "private", "Private"

    class Editability(models.TextChoices):
        RESTRICTED = "restricted", "Restricted"
        INTERNAL = "internal", "FLP Staff"

    path = models.CharField(
        max_length=500,
        unique=True,
        help_text="Full path from root, e.g. 'engineering/devops'",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text="Markdown description shown on directory page.",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="owned_directories",
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    editability = models.CharField(
        max_length=10,
        choices=Editability.choices,
        default=Editability.RESTRICTED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_directories",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "directories"
        ordering = ["path"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        if self.path:
            return f"/c/{self.path}"
        return "/c/"

    def get_ancestors(self):
        """Walk up the parent chain and return list of ancestors."""
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(current)
            current = current.parent
        ancestors.reverse()
        return ancestors

    def get_breadcrumbs(self):
        """Return list of (title, url) tuples for breadcrumb nav."""
        crumbs = [("Home", reverse("root"))]
        for ancestor in self.get_ancestors():
            if not ancestor.path:
                continue  # skip root — already in breadcrumbs
            crumbs.append((ancestor.title, ancestor.get_absolute_url()))
        if self.path:
            crumbs.append((self.title, self.get_absolute_url()))
        return crumbs


class DirectoryRevision(models.Model):
    """Snapshot of a directory at a point in time."""

    directory = models.ForeignKey(
        Directory, on_delete=models.CASCADE, related_name="revisions"
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    visibility = models.CharField(max_length=10)
    editability = models.CharField(max_length=10)
    change_message = models.CharField(max_length=500, blank=True)
    revision_number = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision_number"]
        unique_together = [("directory", "revision_number")]

    def __str__(self):
        return f"{self.directory} v{self.revision_number}"


class DirectoryPermission(models.Model):
    """Granular permission grant on a directory.

    Inherited by all pages and subdirectories within.
    """

    class PermissionType(models.TextChoices):
        VIEW = "view", "View"
        EDIT = "edit", "Edit"
        OWNER = "owner", "Owner"

    directory = models.ForeignKey(
        Directory, on_delete=models.CASCADE, related_name="permissions"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    group = models.ForeignKey(
        "auth.Group",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    permission_type = models.CharField(
        max_length=5,
        choices=PermissionType.choices,
        default=PermissionType.VIEW,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["directory", "user", "permission_type"],
                condition=models.Q(user__isnull=False),
                name="unique_dir_user_perm",
            ),
            models.UniqueConstraint(
                fields=["directory", "group", "permission_type"],
                condition=models.Q(group__isnull=False),
                name="unique_dir_group_perm",
            ),
        ]

    def __str__(self):
        target = self.user or self.group
        return f"{target} → {self.directory} ({self.permission_type})"
