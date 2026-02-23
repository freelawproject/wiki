from django.conf import settings
from django.db import models


class ChangeProposal(models.Model):
    """A proposed change to a wiki page, submitted for owner review."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DENIED = "denied", "Denied"

    page = models.ForeignKey(
        "pages.Page",
        on_delete=models.CASCADE,
        related_name="proposals",
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    proposer_email = models.EmailField(
        blank=True,
        help_text="Email for anonymous proposers to receive notifications.",
    )
    proposed_title = models.CharField(max_length=255)
    proposed_content = models.TextField()
    change_message = models.CharField(max_length=500)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_proposals",
    )
    denial_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["page", "status"]),
        ]

    def __str__(self):
        return f"Proposal for {self.page.title} ({self.status})"
