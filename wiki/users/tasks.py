import sys
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from wiki.lib.favicons import store_favicon
from wiki.users.models import AccessTier, AllowedDomain, SystemConfig

# Re-fetch a domain's favicon at most this often; also retries failures.
FAVICON_REFRESH_AFTER = timezone.timedelta(days=7)
# Cap work per daemon cycle so a large allowlist doesn't stall the loop.
FAVICON_REFRESH_BATCH = 25


def owner_and_manager_emails():
    """Email addresses of the system owner and all active managers (staff).

    Returned sorted and de-duplicated.
    """
    emails = set(
        User.objects.filter(is_active=True, is_staff=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    config = SystemConfig.objects.filter(pk=1).first()
    owner = config.owner if config else None
    if owner and owner.is_active and owner.email:
        emails.add(owner.email)
    return sorted(emails)


def notify_access_change(actor, action, item_type, value, tier=None):
    """Email the owner and managers about a sign-in allowlist change.

    ``action`` is "added"/"updated"/"removed"; ``item_type`` is "domain" or
    "email address". ``tier`` (a value from :class:`AccessTier`) is included on
    adds/updates so the audit mail shows whether the entry is staff or guest.
    Returns the list of recipients that were notified.
    """
    recipients = owner_and_manager_emails()
    if not recipients:
        return []

    tier_clause = ""
    if tier and action in ("added", "updated"):
        label = dict(AccessTier.choices).get(tier, tier)
        tier_clause = f" as a {label.lower()} entry"

    lines = [
        f'{actor.email} {action} the {item_type} "{value}"{tier_clause} on '
        f"the FLP Wiki sign-in allowlist."
    ]
    if action == "removed" and item_type == "domain":
        lines.append(
            "Existing page and directory grants for this domain are kept and "
            "will reactivate automatically if it is re-added."
        )
    lines.append(
        f"Review who can sign in here:\n"
        f"{settings.BASE_URL}{reverse('access_list')}"
    )
    send_mail(
        subject="FLP Wiki sign-in allowlist updated",
        message="\n\n".join(lines),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
    )
    return recipients


def notify_email_access_granted(email):
    """Tell a newly-allowlisted individual address they can now sign in.

    Only used for individual ``AllowedEmail`` grants — a domain has no single
    address to notify.
    """
    body = (
        f"You've been granted access to the FLP Wiki.\n\n"
        f"Sign in with this email address ({email}) here:\n"
        f"{settings.BASE_URL}{reverse('login')}\n\n"
        f"You'll receive a magic sign-in link by email — no password needed."
    )
    send_mail(
        subject="You now have access to the FLP Wiki",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )


def send_magic_link_email(email, raw_token, next_url=""):
    """Send the magic link sign-in email.

    Called synchronously. Fast via SES in prod, instant via
    console backend in dev.

    ``next_url`` (a same-host path, already validated by the caller) rides
    along on the verify link so the user lands back on the page they
    originally requested after signing in.
    """
    params = {"token": raw_token, "email": email}
    if next_url:
        params["next"] = next_url
    verify_url = f"{settings.BASE_URL}{reverse('verify')}?{urlencode(params)}"

    body = (
        f"Click the link below to sign in:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in "
        f"{settings.MAGIC_LINK_EXPIRY_MINUTES} minutes."
    )

    if settings.DEVELOPMENT:
        # Print the URL directly so it's readable in the console
        # (the MIME email output from the console backend mangles
        # URLs with quoted-printable encoding).
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"  Magic sign-in link for {email}:", file=sys.stderr)
        print(f"  {verify_url}", file=sys.stderr)
        print(f"{'=' * 60}\n", file=sys.stderr)

    send_mail(
        subject="Sign in to FLP Wiki",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )


def refresh_domain_favicons():
    """Daemon task: (re)fetch favicons for allowed domains.

    Picks domains never checked or last checked more than
    ``FAVICON_REFRESH_AFTER`` ago (oldest first), bounded to
    ``FAVICON_REFRESH_BATCH`` per run, and refetches each. ``store_favicon``
    is best-effort and always stamps ``favicon_checked_at``, so failures back
    off rather than retrying every cycle.
    """
    cutoff = timezone.now() - FAVICON_REFRESH_AFTER
    stale = AllowedDomain.objects.filter(
        Q(favicon_checked_at__isnull=True) | Q(favicon_checked_at__lt=cutoff)
    ).order_by(
        # Never-checked domains first, then the least-recently checked.
        F("favicon_checked_at").asc(nulls_first=True)
    )[:FAVICON_REFRESH_BATCH]
    for domain in stale:
        store_favicon(domain)
