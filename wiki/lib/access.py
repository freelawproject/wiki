"""Email access control for sign-in.

Access to the wiki is gated by an allowlist managed in the admin: a set of
whole email domains (:class:`AllowedDomain`) plus individual addresses
(:class:`AllowedEmail`). Both the login form and the Django admin call
:func:`is_email_allowed` so the rule lives in exactly one place.
"""

from wiki.users.models import AllowedDomain, AllowedEmail


def is_email_allowed(email):
    """Return True if ``email`` may sign in.

    An address is allowed when it is listed individually or its domain is
    listed. Matching is case-insensitive.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return False

    if AllowedEmail.objects.filter(email=email).exists():
        return True

    domain = email.rsplit("@", 1)[1]
    return (
        bool(domain) and AllowedDomain.objects.filter(domain=domain).exists()
    )
