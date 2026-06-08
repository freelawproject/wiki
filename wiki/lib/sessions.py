"""Session helpers for cutting access immediately."""

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone

from wiki.lib.access import is_email_allowed
from wiki.users.models import UserProfile


def end_sessions_for_users(user_ids):
    """Delete all active sessions belonging to any of ``user_ids``.

    Iterates non-expired sessions and drops those whose authenticated user
    id matches. Used to revoke access at once — archiving a user, or
    removing a domain/email from the sign-in allowlist.
    """
    wanted = {str(uid) for uid in user_ids}
    if not wanted:
        return
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.get_decoded().get(SESSION_KEY) in wanted:
            session.delete()


def revoke_disallowed(users):
    """Cut access for any of ``users`` no longer allowed to sign in.

    Ends their sessions *and* clears any outstanding magic-link token (a
    bearer credential that would otherwise mint a fresh session within its
    expiry window). Users still covered by another allowlist entry are left
    untouched. Call after a domain/email is removed from the allowlist.
    """
    blocked_ids = [u.id for u in users if not is_email_allowed(u.email)]
    if not blocked_ids:
        return
    end_sessions_for_users(blocked_ids)
    UserProfile.objects.filter(user_id__in=blocked_ids).update(
        magic_link_token="", magic_link_expires=None
    )
