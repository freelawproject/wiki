from django.conf import settings
from django.db import models


class PageSubscription(models.Model):
    """Tracks which users are subscribed to page change notifications."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_subscriptions",
    )
    page = models.ForeignKey(
        "pages.Page",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "page")]

    def __str__(self):
        return f"{self.user} → {self.page}"


class DirectorySubscription(models.Model):
    """Tracks which users are subscribed to a directory and all its contents."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="directory_subscriptions",
    )
    directory = models.ForeignKey(
        "directories.Directory",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "directory")]

    def __str__(self):
        return f"{self.user} → {self.directory}"


class SubscriptionExclusion(models.Model):
    """Opt-out from a directory subscription for a specific page or subdirectory.

    Exactly one of ``page`` or ``directory`` must be set (enforced by a
    CheckConstraint).  When a user subscribes to a parent directory but
    wants to stop receiving notifications for a particular child page or
    subdirectory, an exclusion record is created instead of removing the
    broader subscription.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription_exclusions",
    )
    page = models.ForeignKey(
        "pages.Page",
        on_delete=models.CASCADE,
        related_name="subscription_exclusions",
        null=True,
        blank=True,
    )
    directory = models.ForeignKey(
        "directories.Directory",
        on_delete=models.CASCADE,
        related_name="subscription_exclusions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(page__isnull=False, directory__isnull=True)
                    | models.Q(page__isnull=True, directory__isnull=False)
                ),
                name="exclusion_has_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=("user", "page"),
                condition=models.Q(page__isnull=False),
                name="unique_user_page_exclusion",
            ),
            models.UniqueConstraint(
                fields=("user", "directory"),
                condition=models.Q(directory__isnull=False),
                name="unique_user_dir_exclusion",
            ),
        ]

    def __str__(self):
        target = self.page or self.directory
        return f"{self.user} excludes {target}"
