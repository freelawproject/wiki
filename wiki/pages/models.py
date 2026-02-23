from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from django.utils.text import slugify


class Page(models.Model):
    """A wiki page with markdown content."""

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        INTERNAL = "internal", "FLP Staff"
        PRIVATE = "private", "Private"

    class Editability(models.TextChoices):
        RESTRICTED = "restricted", "Restricted"
        INTERNAL = "internal", "FLP Staff"

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    content = models.TextField(blank=True)
    directory = models.ForeignKey(
        "directories.Directory",
        on_delete=models.CASCADE,
        related_name="pages",
        null=True,
        blank=True,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="owned_pages",
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
    change_message = models.CharField(max_length=500, blank=True)
    view_count = models.PositiveIntegerField(
        default=0,
        help_text="Denormalized count, updated periodically from tallies.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_pages",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_pages",
    )
    search_vector = SearchVectorField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["directory", "slug"]),
            GinIndex(fields=["search_vector"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        needs_slug = False
        if not self.slug:
            # New page without a slug: generate from title
            needs_slug = True
        elif self.pk:
            # Existing page: regenerate slug only if title changed
            old_title = (
                Page.objects.filter(pk=self.pk)
                .values_list("title", flat=True)
                .first()
            )
            if old_title and old_title != self.title:
                needs_slug = True

        if needs_slug:
            new_slug = slugify(self.title)
            base_slug = new_slug
            counter = 1
            while (
                Page.objects.filter(slug=new_slug).exclude(pk=self.pk).exists()
            ):
                counter += 1
                new_slug = f"{base_slug}-{counter}"
            self.slug = new_slug

        super().save(*args, **kwargs)
        self._update_search_vector()
        self._update_page_links(**kwargs)

    def _update_page_links(self, **kwargs):
        """Rebuild PageLink rows based on #slug references in content."""
        update_fields = kwargs.get("update_fields")
        if update_fields and "content" not in update_fields:
            return

        from wiki.lib.markdown import WIKI_LINK_RE

        slugs = set(WIKI_LINK_RE.findall(self.content))
        if not slugs:
            PageLink.objects.filter(from_page=self).delete()
            return

        # Resolve slugs to pages
        pages_by_slug = {
            p.slug: p
            for p in Page.objects.filter(slug__in=slugs).exclude(pk=self.pk)
        }

        # Check redirects for unresolved slugs
        missing = slugs - set(pages_by_slug.keys())
        if missing:
            for r in SlugRedirect.objects.filter(
                old_slug__in=missing
            ).select_related("page"):
                if r.page_id != self.pk:
                    pages_by_slug[r.old_slug] = r.page

        target_pages = set(pages_by_slug.values())

        # Replace all links atomically
        PageLink.objects.filter(from_page=self).delete()
        if target_pages:
            PageLink.objects.bulk_create(
                [PageLink(from_page=self, to_page=tp) for tp in target_pages],
                ignore_conflicts=True,
            )

    def _update_search_vector(self):
        """Update the search_vector for this page in the DB."""
        Page.objects.filter(pk=self.pk).update(
            search_vector=SearchVector("title", weight="A")
            + SearchVector("content", weight="B")
        )

    @property
    def content_path(self):
        """Path used in URL patterns (dir/slug or just slug)."""
        if self.directory and self.directory.path:
            return f"{self.directory.path}/{self.slug}"
        return self.slug

    def get_absolute_url(self):
        if self.directory:
            return f"/c/{self.directory.path}/{self.slug}"
        return f"/c/{self.slug}"


class PageRevision(models.Model):
    """Full snapshot of a page at a point in time."""

    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="revisions"
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    change_message = models.CharField(max_length=500, blank=True)
    revision_number = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision_number"]
        unique_together = [("page", "revision_number")]

    def __str__(self):
        return f"{self.page.title} (v{self.revision_number})"


class PagePermission(models.Model):
    """Granular permission grant on a page."""

    class PermissionType(models.TextChoices):
        VIEW = "view", "View"
        EDIT = "edit", "Edit"
        OWNER = "owner", "Owner"

    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="permissions"
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
                fields=["page", "user", "permission_type"],
                condition=models.Q(user__isnull=False),
                name="unique_page_user_perm",
            ),
            models.UniqueConstraint(
                fields=["page", "group", "permission_type"],
                condition=models.Q(group__isnull=False),
                name="unique_page_group_perm",
            ),
        ]

    def __str__(self):
        target = self.user or self.group
        return f"{target} → {self.page} ({self.permission_type})"


class PageLink(models.Model):
    """Tracks #slug wiki links between pages, updated on save."""

    from_page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="outgoing_links"
    )
    to_page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="incoming_links"
    )

    class Meta:
        unique_together = [("from_page", "to_page")]

    def __str__(self):
        return f"{self.from_page.slug} → {self.to_page.slug}"


class FileUpload(models.Model):
    """File attached to a wiki page, stored in S3."""

    page = models.ForeignKey(
        Page,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploads",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    file = models.FileField(upload_to="uploads/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename


class SlugRedirect(models.Model):
    """Maps old slugs to current pages to preserve wiki links."""

    old_slug = models.SlugField(max_length=255, unique=True)
    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="slug_redirects"
    )

    def __str__(self):
        return f"{self.old_slug} → {self.page.slug}"


class PageViewTally(models.Model):
    """Individual page view records, summed periodically into
    Page.view_count."""

    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="view_tallies"
    )
    count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["page", "created_at"]),
        ]
