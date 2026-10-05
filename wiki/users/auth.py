import logging

from django.contrib.auth.models import User
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from wiki.lib.access import is_email_allowed
from wiki.lib.users import provision_user

logger = logging.getLogger(__name__)


class CourtListenerOIDCBackend(OIDCAuthenticationBackend):
    """Sign in with a CourtListener account.

    Matches the linked ``sub`` first, then a verified email. New users are
    provisioned only when their email is on the allowlist.
    """

    def verify_claims(self, claims):
        return bool(
            claims.get("sub")
            and claims.get("email")
            and claims.get("email_verified") is True
        )

    def filter_users_by_claims(self, claims):
        by_sub = User.objects.filter(profile__courtlistener_sub=claims["sub"])
        if by_sub.exists():
            return by_sub
        email = claims["email"].strip()
        by_email = User.objects.filter(username__iexact=email)
        if by_email.count() > 1:
            return by_email.filter(username=email.lower())
        return by_email

    def update_user(self, user, claims):
        if not user.is_active or not is_email_allowed(user.email):
            return None
        profile = provision_user(user.username).profile
        if profile.courtlistener_sub and profile.courtlistener_sub != str(
            claims["sub"]
        ):
            logger.warning(
                "CourtListener sub mismatch for wiki user %s", user.pk
            )
            return None
        if not profile.courtlistener_sub:
            profile.courtlistener_sub = str(claims["sub"])
            profile.save(update_fields=["courtlistener_sub"])
        return user

    def create_user(self, claims):
        email = claims["email"].strip().lower()
        if not is_email_allowed(email):
            return None
        user = provision_user(email)
        profile = user.profile
        profile.courtlistener_sub = str(claims["sub"])
        if not profile.display_name:
            profile.display_name = claims.get("name", "")
        profile.save(update_fields=["courtlistener_sub", "display_name"])
        return user
