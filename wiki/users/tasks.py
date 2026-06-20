import sys

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.urls import reverse

from wiki.users.models import AccessTier, SystemConfig


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


def send_magic_link_email(email, raw_token):
    """Send the magic link sign-in email.

    Called synchronously. Fast via SES in prod, instant via
    console backend in dev.
    """
    verify_url = (
        f"{settings.BASE_URL}{reverse('verify')}"
        f"?token={raw_token}&email={email}"
    )

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
