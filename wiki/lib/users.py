"""Shared user display + handle utilities.

Users are addressed by a unique ``UserProfile.handle`` (the public @-name
used in mentions, permission forms, and the activity feed). The handle is
derived from the email local part and disambiguated on collision with the
domain's :attr:`AllowedDomain.suffix` (or a number when there's no domain
suffix). See ``assign_handle``.
"""

import re

from wiki.users.models import AllowedDomain, UserProfile

HANDLE_MAX = 64

# Characters allowed in a handle. Matches the @-mention regex charset
# (@([a-zA-Z][a-zA-Z0-9._-]*)) and is URL-safe for activity/<handle>/.
_HANDLE_STRIP_RE = re.compile(r"[^a-z0-9._-]+")


def display_name(user):
    """Return display name for a user, never showing a full email.

    Priority: profile.display_name > handle > first part of email > "Unknown"
    """
    if not user:
        return "Unknown"
    if hasattr(user, "profile"):
        try:
            profile = user.profile
            if profile.display_name:
                return profile.display_name
            if profile.handle:
                return profile.handle
        except Exception:
            pass
    email = getattr(user, "email", "")
    if email and "@" in email:
        return email.split("@")[0]
    return "Unknown"


def sanitize_handle_base(email):
    """Derive a handle base from an email's local part.

    Lowercase it, drop anything outside ``[a-z0-9._-]``, and guarantee a
    leading letter (the @-mention regex requires one). Leaves headroom in
    the 64-char field for a disambiguating suffix.
    """
    local = (email or "").split("@", 1)[0].lower()
    base = _HANDLE_STRIP_RE.sub("", local).lstrip("._-")
    if not base or not base[0].isalpha():
        base = "u" + base
    return base[:50]


def _compose(base, tail):
    """Build a handle from ``base`` and an optional ``tail``, within length."""
    if not tail:
        return base[:HANDLE_MAX]
    keep = HANDLE_MAX - len(tail) - 1
    return f"{base[:keep]}-{tail}"


def _suffix_for_email(email):
    """The collision suffix for an address: its domain's suffix, else None."""
    domain = email.split("@", 1)[1] if "@" in email else ""
    row = AllowedDomain.objects.filter(domain=domain).first()
    return row.suffix if row else None


def assign_handle(profile):
    """Assign and persist a unique handle to ``profile``.

    Idempotent: returns the existing handle if already set. The first
    claimant of a base keeps it; a colliding account gets ``<base>-<suffix>``
    (its domain's suffix), or ``<base>-2`` when the address has no domain
    suffix (an individually-allowed email) or the suffixed handle is taken.
    """
    if profile.handle:
        return profile.handle

    email = profile.user.email
    base = sanitize_handle_base(email)

    def taken(h):
        return (
            UserProfile.objects.filter(handle=h)
            .exclude(pk=profile.pk)
            .exists()
        )

    candidate = _compose(base, "")
    if taken(candidate):
        suffix = _suffix_for_email(email)
        if suffix:
            candidate = _compose(base, suffix)
            n = 2
            while taken(candidate):
                candidate = _compose(base, f"{suffix}-{n}")
                n += 1
        else:
            n = 2
            candidate = _compose(base, str(n))
            while taken(candidate):
                n += 1
                candidate = _compose(base, str(n))

    profile.handle = candidate
    profile.save(update_fields=["handle"])
    return candidate


def user_by_handle(handle):
    """Resolve an @-handle to its user (exact, unique). None if not found."""
    if not handle:
        return None
    profile = (
        UserProfile.objects.filter(handle=handle.strip().lower())
        .select_related("user")
        .first()
    )
    return profile.user if profile else None
