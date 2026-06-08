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
    handle = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text=(
            "Unique public @-handle, assigned at first sign-in. Derived "
            "from the email local part, disambiguated on collision."
        ),
    )
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


class AllowedDomain(models.Model):
    """An email domain whose addresses are allowed to sign in.

    Any address ending in ``@<domain>`` may request a magic link. Stored
    lowercase without a leading ``@`` or ``.``.
    """

    domain = models.CharField(max_length=255, unique=True)
    suffix = models.CharField(
        max_length=32,
        unique=True,
        help_text=(
            "Short slug appended to a handle when it collides with an "
            "existing one, e.g. 'flp' turns a colliding mike@free.law into "
            "'mike-flp'. Used only on actual collisions."
        ),
    )
    note = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional reminder of why this domain is allowed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["domain"]

    def __str__(self):
        return self.domain

    @staticmethod
    def normalize(domain):
        return domain.strip().lower().lstrip("@").strip(".")

    @staticmethod
    def normalize_suffix(suffix):
        return suffix.strip().lower()

    def save(self, *args, **kwargs):
        self.domain = self.normalize(self.domain)
        self.suffix = self.normalize_suffix(self.suffix)
        super().save(*args, **kwargs)


class AllowedEmail(models.Model):
    """A single email address allowed to sign in.

    Use this to grant access to an individual whose domain is not allowed
    wholesale (e.g. an outside contractor). Stored lowercase.
    """

    email = models.EmailField(unique=True)
    note = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional reminder of why this address is allowed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email

    @staticmethod
    def normalize(email):
        return email.strip().lower()

    def save(self, *args, **kwargs):
        self.email = self.normalize(self.email)
        super().save(*args, **kwargs)
