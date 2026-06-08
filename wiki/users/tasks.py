import sys

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.urls import reverse

from wiki.users.models import SystemConfig


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


def notify_access_change(actor, action, item_type, value):
    """Email the owner and managers about a sign-in allowlist change.

    ``action`` is "added" or "removed"; ``item_type`` is "domain" or
    "email address". Returns the list of recipients that were notified.
    """
    recipients = owner_and_manager_emails()
    if not recipients:
        return []

    body = (
        f'{actor.email} {action} the {item_type} "{value}" on the FLP Wiki '
        f"sign-in allowlist.\n\n"
        f"Review who can sign in here:\n"
        f"{settings.BASE_URL}{reverse('access_list')}"
    )
    send_mail(
        subject="FLP Wiki sign-in allowlist updated",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
    )
    return recipients


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
