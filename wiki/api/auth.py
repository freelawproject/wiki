"""CourtListener bearer tokens on the JSON API.

CourtListener is the OAuth server and this wiki is a resource server with a
confidential client registered there. A request's bearer token is
introspected (RFC 7662, authenticated with that client) to check that it is
live and carries the ``wiki`` scope; the userinfo endpoint then gives the
account's verified email. That email is let in exactly as a magic-link
sign-in would be: an allowlisted address gets (or mints) its wiki account,
anyone else is anonymous and sees public pages only.
"""

import logging
from functools import wraps

import httpx
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from django.utils.cache import add_never_cache_headers

from wiki.lib.access import is_email_allowed
from wiki.lib.users import provision_user

logger = logging.getLogger(__name__)


def verified_email_for(token):
    """The verified email behind a CourtListener token carrying the ``wiki``
    scope, or None for a token that is invalid or lacks it."""
    if not (
        settings.COURTLISTENER_CLIENT_ID
        and settings.COURTLISTENER_CLIENT_SECRET
    ):
        logger.warning(
            "COURTLISTENER_CLIENT_ID/SECRET unset; bearer tokens are rejected"
        )
        return None
    with httpx.Client(base_url=settings.COURTLISTENER_URL, timeout=10) as cl:
        introspection = cl.post(
            "/o/introspect/",
            data={"token": token},
            auth=(
                settings.COURTLISTENER_CLIENT_ID,
                settings.COURTLISTENER_CLIENT_SECRET,
            ),
        )
        introspection.raise_for_status()
        info = introspection.json()
        if (
            not info.get("active")
            or "wiki" not in info.get("scope", "").split()
        ):
            return None
        userinfo = cl.get(
            "/o/userinfo/", headers={"Authorization": f"Bearer {token}"}
        )
        userinfo.raise_for_status()
    claims = userinfo.json()
    return claims["email"].lower() if claims.get("email_verified") else None


def bearer_auth(view):
    """Make ``request.user`` the account behind the request's bearer token.

    A bad token is a 401. Without a token the view sees the request's own
    (session or anonymous) user. Responses vary by token, so they are
    marked uncacheable.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        scheme, _, token = request.headers.get("Authorization", "").partition(
            " "
        )
        if scheme.lower() == "bearer":
            email = verified_email_for(token.strip())
            if email is None:
                return JsonResponse(
                    {"error": "invalid_token"},
                    status=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user = provision_user(email) if is_email_allowed(email) else None
            request.user = user or AnonymousUser()
        response = view(request, *args, **kwargs)
        add_never_cache_headers(response)
        return response

    return wrapper
