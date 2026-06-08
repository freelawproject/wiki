"""Shared user display utilities."""

from django.contrib.auth.models import User


def display_name(user):
    """Return display name for a user, never showing a full email.

    Priority: profile.display_name > first part of email > "Unknown"
    """
    if not user:
        return "Unknown"
    if hasattr(user, "profile"):
        try:
            name = user.profile.display_name
            if name:
                return name
        except Exception:
            pass
    email = getattr(user, "email", "")
    if email and "@" in email:
        return email.split("@")[0]
    return "Unknown"


def user_by_local_part(local_part):
    """Resolve a username / @-mention (an email local part) to one user.

    The wiki refers to users by the local part of their email. Once more
    than one sign-in domain is allowed, two accounts can share a local part
    (e.g. ``alice@free.law`` and ``alice@example.org``). In that case the
    reference is ambiguous, so we return ``None`` rather than guess at a
    user — guessing would otherwise grant page access to, or email a page
    snippet to, the wrong person. Also returns ``None`` when nothing matches.
    """
    if not local_part:
        return None
    # Fetch at most two rows: one means unambiguous, two means ambiguous.
    matches = list(
        User.objects.filter(email__istartswith=local_part + "@")[:2]
    )
    if len(matches) == 1:
        return matches[0]
    return None
