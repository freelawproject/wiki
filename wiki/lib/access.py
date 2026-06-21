"""Email access control for sign-in.

Access to the wiki is gated by an allowlist managed in the admin: a set of
whole email domains (:class:`AllowedDomain`) plus individual addresses
(:class:`AllowedEmail`). Both the login form and the Django admin call
:func:`is_email_allowed` so the rule lives in exactly one place.
"""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from wiki.users.models import AccessTier, AllowedDomain, AllowedEmail


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


def resolve_tier(email):
    """Return the access tier (``staff``/``guest``) for ``email``.

    An exact :class:`AllowedEmail` match wins over the address's domain, so an
    individual can be elevated to staff (or held back to guest) even when
    their domain says otherwise. Returns ``None`` if the address is not on the
    allowlist at all.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1]

    row = (
        AllowedEmail.objects.filter(email=email)
        .values_list("tier", flat=True)
        .first()
    )
    if row is not None:
        return row
    return (
        AllowedDomain.objects.filter(domain=domain)
        .values_list("tier", flat=True)
        .first()
    )


def is_internal_user(user):
    """Return True if ``user`` is part of the "internal" (staff) audience.

    Staff see ``internal`` content without an explicit grant — the audience
    that *every* authenticated user used to be before outside orgs could sign
    in. Guests get ``public`` content plus only what's explicitly
    granted to them, their group, or their domain.

    The system owner and managers always count as staff (both carry
    ``is_staff``/``is_superuser`` — set in ``login_view`` and ``admin_toggle``);
    everyone else is staff only if their allowlist entry's tier says so.
    Cached on the user object for the duration of the request.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    cached = getattr(user, "_is_internal_user_cache", None)
    if cached is not None:
        return cached

    result = bool(user.is_staff or user.is_superuser) or (
        resolve_tier(user.email) == AccessTier.STAFF
    )
    user._is_internal_user_cache = result
    return result
