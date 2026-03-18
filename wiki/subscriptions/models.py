from django.conf import settings
from django.db import models


class SubscriptionStatus(models.TextChoices):
    SUBSCRIBED = "subscribed", "Subscribed"
    UNSUBSCRIBED = "unsubscribed", "Unsubscribed"


class PageSubscription(models.Model):
    """Per-user subscription override for a specific page.

    An explicit SUBSCRIBED or UNSUBSCRIBED status overrides whatever
    the user would inherit from directory subscriptions.  The absence
    of a record means "inherit from the nearest ancestor directory
    that has a DirectorySubscription for this user".
    """

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
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.SUBSCRIBED,
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "page")]

    def __str__(self):
        return f"{self.user} → {self.page} ({self.status})"


class DirectorySubscription(models.Model):
    """Per-user subscription override for a directory.

    An explicit SUBSCRIBED or UNSUBSCRIBED status is inherited by all
    descendant directories and pages that do not have their own
    override.  The absence of a record means "inherit from parent
    directory".  The implicit default at the root is UNSUBSCRIBED.
    """

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
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.SUBSCRIBED,
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "directory")]

    def __str__(self):
        return f"{self.user} → {self.directory} ({self.status})"
