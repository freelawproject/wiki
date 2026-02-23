import hashlib

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    """Extended profile for wiki users.

    Auto-created on first login. Stores display name, Gravatar URL,
    and magic link auth tokens.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=255, blank=True)
    gravatar_url = models.URLField(blank=True)
    magic_link_token = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hash of the magic link token",
    )
    magic_link_expires = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name or self.user.email

    def set_magic_token(self, raw_token):
        """Store hashed token and set expiry."""
        self.magic_link_token = hashlib.sha256(raw_token.encode()).hexdigest()
        self.magic_link_expires = timezone.now() + timezone.timedelta(
            minutes=settings.MAGIC_LINK_EXPIRY_MINUTES
        )

    def verify_magic_token(self, raw_token):
        """Verify a raw token against the stored hash."""
        if not self.magic_link_token or not self.magic_link_expires:
            return False
        if timezone.now() > self.magic_link_expires:
            return False
        hashed = hashlib.sha256(raw_token.encode()).hexdigest()
        return hashed == self.magic_link_token

    def clear_magic_token(self):
        """Clear the magic link token after use."""
        self.magic_link_token = ""
        self.magic_link_expires = None

    @staticmethod
    def gravatar_url_for_email(email):
        """Generate Gravatar URL for an email address."""
        email_hash = hashlib.md5(email.strip().lower().encode()).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?d=mp&s=80"


class SystemConfig(models.Model):
    """Singleton configuration. pk=1 always.

    Tracks the system owner (first user to log in).
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "System Configuration"

    def __str__(self):
        return "System Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
