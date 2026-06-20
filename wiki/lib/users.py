"""Shared user display + handle utilities.

Users are addressed by a unique ``UserProfile.handle`` (the public @-name
used in mentions, permission forms, and the activity feed). The handle is
derived from the email local part and disambiguated on collision with the
domain's :attr:`AllowedDomain.suffix` (or a number when there's no domain
suffix). See ``assign_handle``.
"""

import re

from django.db import IntegrityError, transaction

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
    # Lowercase to match AllowedDomain.save(), which stores domains lowercase;
    # an admin-created User may carry a mixed-case email.
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    row = AllowedDomain.objects.filter(domain=domain).first()
    return row.suffix if row else None


def _handle_candidates(base, suffix):
    """Yield handle candidates in priority order, indefinitely.

    Bare base first, then the domain suffix (or numbers when there's no
    suffix), then numbered variants — so collisions disambiguate the way
    the design specifies.
    """
    yield _compose(base, "")
    if suffix:
        yield _compose(base, suffix)
        n = 2
        while True:
            yield _compose(base, f"{suffix}-{n}")
            n += 1
    else:
        n = 2
        while True:
            yield _compose(base, str(n))
            n += 1


def assign_handle(profile):
    """Assign and persist a unique handle to ``profile``.

    Idempotent: returns the existing handle if already set. The first
    claimant of a base keeps it; a colliding account gets ``<base>-<suffix>``
    (its domain's suffix), or ``<base>-2`` when the address has no domain
    suffix (an individually-allowed email) or the suffixed handle is taken.

    The ``taken`` pre-check skips known collisions, but the unique constraint
    is the real arbiter: two concurrent first sign-ins can both pass the
    pre-check, so we catch ``IntegrityError`` and fall through to the next
    candidate. ``transaction.atomic`` wraps each attempt as a savepoint so a
    failed insert doesn't poison the surrounding transaction on PostgreSQL.
    """
    if profile.handle:
        return profile.handle

    email = profile.user.email
    base = sanitize_handle_base(email)
    suffix = _suffix_for_email(email)

    def taken(h):
        return (
            UserProfile.objects.filter(handle=h)
            .exclude(pk=profile.pk)
            .exists()
        )

    for candidate in _handle_candidates(base, suffix):
        if taken(candidate):
            continue
        profile.handle = candidate
        try:
            with transaction.atomic():
                profile.save(update_fields=["handle"])
            return candidate
        except IntegrityError:
            # Lost the race for this handle; try the next candidate.
            continue


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
