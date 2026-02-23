from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class EditLock(models.Model):
    """Advisory lock indicating a user is currently editing a page or directory.

    Exactly one of `page` or `directory` must be set (enforced by
    CheckConstraint).  Locks expire after 30 minutes and are released
    on successful save.
    """

    LOCK_DURATION = timedelta(minutes=30)

    page = models.ForeignKey(
        "pages.Page",
        on_delete=models.CASCADE,
        related_name="edit_locks",
        null=True,
        blank=True,
    )
    directory = models.ForeignKey(
        "directories.Directory",
        on_delete=models.CASCADE,
        related_name="edit_locks",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="edit_locks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="editlock_exactly_one_target",
                condition=(
                    models.Q(page__isnull=False, directory__isnull=True)
                    | models.Q(page__isnull=True, directory__isnull=False)
                ),
            ),
        ]
        indexes = [
            models.Index(
                fields=["page", "expires_at"],
                name="editlock_page_expires",
            ),
            models.Index(
                fields=["directory", "expires_at"],
                name="editlock_dir_expires",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + self.LOCK_DURATION
        super().save(*args, **kwargs)

    def __str__(self):
        target = self.page or self.directory
        return f"EditLock({target}, user={self.user})"
