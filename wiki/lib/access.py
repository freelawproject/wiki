"""Email access control for sign-in.

Access to the wiki is gated by an allowlist managed in the admin: a set of
whole email domains (:class:`AllowedDomain`) plus individual addresses
(:class:`AllowedEmail`). Both the login form and the Django admin call
:func:`is_email_allowed` so the rule lives in exactly one place.
"""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from wiki.users.models import AllowedDomain, AllowedEmail


def is_email_allowed(email):
    """Return True if ``email`` may sign in.

    An address is allowed when it is listed individually or its domain is
    listed. Matching is case-insensitive.

    This is a security boundary, so it validates the address itself rather
    than trusting callers to have done so. It requires a single ``@`` (the
    domain is then unambiguous) and a well-formed, single addr-spec, which
    rejects the classic allowlist-bypass shapes — multiple ``@``
    (``evil@evil.com@free.law``), quoted local parts hiding an ``@``
    (``"evil@evil.com"@free.law``), and an empty local part (``@free.law``).

    Plus-addressing is rejected: ``mike+foo@free.law`` delivers to
    ``mike@free.law``, so allowing it would let a single mailbox mint
    unlimited distinct accounts and sidestep per-account archiving.
    (Dot-addressing — ``m.ike@gmail.com`` — is the same class of problem
    but can't be handled with a blanket rule; it needs provider-aware
    canonicalization, tracked separately.)
    """
    email = (email or "").strip().lower()

    # A single "@" makes the local part / domain split unambiguous; the
    # rest of the parsing below depends on it.
    if email.count("@") != 1:
        return False
    try:
        validate_email(email)
    except ValidationError:
        return False

    local, domain = email.split("@")
    if not local or not domain:
        return False

    # Reject plus-addressing (see docstring): one mailbox must map to one
    # sign-in identity.
    if "+" in local:
        return False

    if AllowedEmail.objects.filter(email=email).exists():
        return True
    return AllowedDomain.objects.filter(domain=domain).exists()
