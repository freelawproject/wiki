"""Session helpers for cutting access immediately."""

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone


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
