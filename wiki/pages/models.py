import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models, transaction
from django.utils.text import slugify

from wiki.lib.path_utils import page_path_conflicts_with_directory


class ActivePageManager(models.Manager):
    """Default manager — excludes soft-deleted pages."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Page(models.Model):
    """A wiki page with markdown content."""

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        INTERNAL = "internal", "FLP Staff"
        PRIVATE = "private", "Private"
        INHERIT = "inherit", "Inherit"

    class Editability(models.TextChoices):
        RESTRICTED = "restricted", "Restricted"
        INTERNAL = "internal", "FLP Staff"
        INHERIT = "inherit", "Inherit"

    class SitemapStatus(models.TextChoices):
        INCLUDE = "include", "Yes"
        EXCLUDE = "exclude", "No"
        INHERIT = "inherit", "Inherit"

    class LlmsTxtStatus(models.TextChoices):
        EXCLUDE = "exclude", "No"
        INCLUDE = "include", "Yes"
        OPTIONAL = "optional", "On request"
        INHERIT = "inherit", "Inherit"

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
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
    seo_description = models.CharField(
        max_length=300,
        blank=True,
        help_text="Short summary for search engines and llms.txt. "
        "If blank, auto-generated from first words of content.",
    )
    in_sitemap = models.CharField(
        max_length=10,
        choices=SitemapStatus.choices,
        default=SitemapStatus.INCLUDE,
        help_text="Include this page in the sitemap.xml file.",
    )
    in_llms_txt = models.CharField(
        max_length=10,
        choices=LlmsTxtStatus.choices,
        default=LlmsTxtStatus.EXCLUDE,
        help_text="Whether to list this page in llms.txt.",
    )
    data_source_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="URL returning JSON whose values replace [[ key ]] "
        "placeholders in this page's content.",
    )
    data_source_ttl = models.PositiveIntegerField(
        default=300,
        help_text="How many seconds to cache the data source response.",
    )
    change_message = models.CharField(max_length=500, blank=True)
    is_pinned = models.BooleanField(
        default=False,
        help_text="Pinned pages appear at the top of directory listings.",
    )
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
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_pages",
    )

    objects = ActivePageManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["directory", "slug"]),
            GinIndex(fields=["search_vector"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["directory", "slug"],
                condition=models.Q(is_deleted=False),
                name="unique_active_slug_per_directory",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Persist the page, auto-generate/rescope the slug, and fan out
        bookkeeping (search vector, link graph, collision rewrites).

        ``_skip_collision_rewrite=True`` suppresses the qualify-bare-links
        pass. It's set by the collision handler when it recursively saves
        the *linking* pages, so those saves don't re-trigger another round
        of rewrites against the page that started it all.
        """
        skip_collision_rewrite = kwargs.pop("_skip_collision_rewrite", False)

        needs_slug = False
        if not self.slug:
            # New page without a slug: generate from title
            needs_slug = True
        elif self.pk:
            # Existing page: regenerate slug only if title changed
            # Use all_objects so this works when restoring deleted pages
            old_title = (
                Page.all_objects.filter(pk=self.pk)
                .values_list("title", flat=True)
                .first()
            )
            if old_title and old_title != self.title:
                needs_slug = True

        if needs_slug:
            new_slug = slugify(self.title)
            base_slug = new_slug
            counter = 1
            # Uniqueness is scoped per directory — only collide with siblings
            while Page.objects.filter(
                directory=self.directory, slug=new_slug
            ).exclude(
                pk=self.pk
            ).exists() or page_path_conflicts_with_directory(
                new_slug, self.directory
            ):
                counter += 1
                new_slug = f"{base_slug}-{counter}"
            self.slug = new_slug

        super().save(*args, **kwargs)
        self._update_search_vector()
        self._update_page_links(**kwargs)
        if not skip_collision_rewrite:
            self._qualify_bare_links_on_collision()

    def _qualify_bare_links_on_collision(self):
        """If this page's slug collides with others, qualify bare links to them.

        When saving introduces or continues a slug collision (another active
        page shares ``self.slug`` in a different directory), walk every page
        that links to those sibling pages and rewrite their bare ``#slug``
        references to the sibling's qualified ``#dir/slug`` form. This keeps
        historical links pointing at the intended page even as the bare form
        becomes ambiguous.
        """
        from wiki.lib.markdown import qualify_bare_links

        siblings = list(
            Page.objects.filter(slug=self.slug)
            .exclude(pk=self.pk)
            .select_related("directory")
        )
        if not siblings:
            return

        for sibling in siblings:
            sibling_path = sibling.content_path
            linking_pages = list(
                Page.objects.filter(outgoing_links__to_page=sibling)
                .exclude(pk=self.pk)
                .exclude(pk=sibling.pk)
                .distinct()
            )
            for linking_page in linking_pages:
                new_content = qualify_bare_links(
                    linking_page.content, sibling.slug, sibling_path
                )
                if new_content == linking_page.content:
                    continue
                linking_page.content = new_content
                # Atomic: the content update and its revision row must
                # succeed or fail together, or history loses track of
                # why the content changed.
                with transaction.atomic():
                    linking_page.save(
                        update_fields=["content", "updated_at"],
                        _skip_collision_rewrite=True,
                    )
                    linking_page.create_revision(
                        user=None,
                        change_message=(
                            f"Qualify wiki links to #{sibling.slug} "
                            f"after slug collision"
                        ),
                    )

    def soft_delete(self, user):
        """Soft-delete this page instead of permanently removing it."""
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def _update_page_links(self, **kwargs):
        """Rebuild PageLink rows from wiki-link and internal-URL references."""
        update_fields = kwargs.get("update_fields")
        if update_fields and "content" not in update_fields:
            return

        # Inline import to avoid circular dependency (pages/models ↔ lib/markdown)
        from wiki.lib.markdown import (
            extract_all_wiki_references,
            extract_references_from_internal_urls,
            resolve_references,
        )

        references = extract_all_wiki_references(self.content)
        references |= extract_references_from_internal_urls(self.content)

        if not references:
            PageLink.objects.filter(from_page=self).delete()
            return

        resolved = resolve_references(references, exclude_pk=self.pk)
        target_ids = {p.pk for p in resolved.values()}

        with transaction.atomic():
            PageLink.objects.filter(from_page=self).delete()
            if target_ids:
                PageLink.objects.bulk_create(
                    [
                        PageLink(from_page=self, to_page_id=tp_id)
                        for tp_id in target_ids
                    ],
                    ignore_conflicts=True,
                )

    def _update_search_vector(self):
        """Update the search_vector for this page in the DB."""
        Page.all_objects.filter(pk=self.pk).update(
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
        if self.directory and self.directory.path:
            return f"/c/{self.directory.path}/{self.slug}"
        return f"/c/{self.slug}"

    def create_revision(self, user, change_message=None):
        """Create a new revision snapshot of this page."""
        last = self.revisions.order_by("-revision_number").first()
        rev_num = (last.revision_number + 1) if last else 1
        return PageRevision.objects.create(
            page=self,
            title=self.title,
            content=self.content,
            change_message=change_message or self.change_message,
            revision_number=rev_num,
            created_by=user,
        )


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
    file = models.FileField(upload_to="uploads/%Y/%m/", max_length=1000)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    optimization_gain = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Bytes saved by optimization. "
            "Null=pending, positive=saved, negative=grew, 0=error."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename


class PendingUpload(models.Model):
    """Tracks authorized presigned S3 uploads awaiting confirmation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    s3_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    expected_size = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pending: {self.original_filename}"


class SlugRedirect(models.Model):
    """Maps old (directory, slug) pairs to current pages to preserve wiki links."""

    directory = models.ForeignKey(
        "directories.Directory",
        on_delete=models.CASCADE,
        related_name="slug_redirects",
        null=True,
        blank=True,
    )
    old_slug = models.SlugField(max_length=255)
    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="slug_redirects"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["directory", "old_slug"],
                name="unique_slug_redirect_per_directory",
            ),
        ]

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
