import sys

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse


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
