"""CourtListener bearer tokens on the JSON API.

CourtListener is the OAuth server and this wiki is a resource server with a
confidential client registered there. A request's bearer token is
introspected (RFC 7662, authenticated with that client) to check that it is
live and carries the ``wiki`` scope; the userinfo endpoint then gives the
account's verified email. That email is let in exactly as a magic-link
sign-in would be: an allowlisted address gets (or mints) its wiki account,
anyone else is anonymous and sees public pages only.
"""

import hashlib
import logging
import time
from functools import wraps

import httpx
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, update_last_login
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.cache import add_never_cache_headers

from wiki.lib.access import is_email_allowed
from wiki.lib.users import provision_user

logger = logging.getLogger(__name__)

# How long CourtListener's answer about a token is remembered, so a burst
# of requests costs one round trip. A revoked token keeps working for up
# to this long. Rejections are remembered briefly too.
TOKEN_CACHE_SECONDS = 300
REJECTION_CACHE_SECONDS = 30


def cached_verified_email_for(token):
    """``verified_email_for``, remembered per token for a few minutes."""
    key = "cl-token:" + hashlib.sha256(token.encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    email, ttl = verified_email_for(token)
    cache.set(key, email or "", ttl)
    return email


def verified_email_for(token):
    """The verified email behind a CourtListener token carrying the ``wiki``
    scope (None for a token that is invalid or lacks it), and how many
    seconds that answer may be remembered."""
    if not (
        settings.COURTLISTENER_CLIENT_ID
        and settings.COURTLISTENER_CLIENT_SECRET
    ):
        logger.warning(
            "COURTLISTENER_CLIENT_ID/SECRET unset; bearer tokens are rejected"
        )
        return None, REJECTION_CACHE_SECONDS
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
            return None, REJECTION_CACHE_SECONDS
        userinfo = cl.get(
            "/o/userinfo/", headers={"Authorization": f"Bearer {token}"}
        )
        # Refused for the token's sake (e.g. no openid scope), not ours.
        if userinfo.status_code in (401, 403):
            return None, REJECTION_CACHE_SECONDS
        userinfo.raise_for_status()
    claims = userinfo.json()
    if not (claims.get("email") and claims.get("email_verified")):
        return None, REJECTION_CACHE_SECONDS
    # Never remember a token past its own expiry.
    ttl = min(TOKEN_CACHE_SECONDS, int(info.get("exp", 0)) - int(time.time()))
    return claims["email"].lower(), max(ttl, 1)


def bearer_auth(view):
    """Make ``request.user`` the account behind the request's bearer token.

    A bad token is a 401; CourtListener being unreachable is a 503. Without
    a token the view sees the request's own (session or anonymous) user.
    Responses vary by token, so they are marked uncacheable.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        scheme, _, token = request.headers.get("Authorization", "").partition(
            " "
        )
        if scheme.lower() == "bearer":
            try:
                email = cached_verified_email_for(token.strip())
            except httpx.HTTPError:
                logger.exception("CourtListener could not check a token")
                return JsonResponse(
                    {"error": "courtlistener_unavailable"}, status=503
                )
            if email is None:
                return JsonResponse(
                    {"error": "invalid_token"},
                    status=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user = provision_user(email) if is_email_allowed(email) else None
            if user and user.last_login is None:
                # Count the first use as a sign-in.
                update_last_login(None, user)
            request.user = user or AnonymousUser()
        response = view(request, *args, **kwargs)
        add_never_cache_headers(response)
        return response

    return wrapper
