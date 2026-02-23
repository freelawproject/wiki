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
