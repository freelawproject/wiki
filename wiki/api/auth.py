"""CourtListener bearer tokens on the JSON API.

CourtListener is the OAuth server and this wiki is a resource server with a
confidential client registered there. A request's bearer token is
introspected (RFC 7662, authenticated with that client) to check that it is
live. If it carries the ``wiki`` scope, the userinfo endpoint then gives the
account's verified email, which is let in exactly as a magic-link sign-in
would be: an allowlisted address gets (or mints) its wiki account, anyone
else is anonymous and sees public pages only.

A live token without the ``wiki`` scope is anonymous too, rather than
refused: it gets no more than a request without a token would, and an MCP
connection made before the wiki tools existed can read public pages without
reconnecting. Only a token CourtListener rejects is a 401.
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
from wiki.lib.ratelimiter import ratelimit_token_check
from wiki.lib.users import provision_user

logger = logging.getLogger(__name__)

# How long CourtListener's answer about a token is remembered, so a burst
# of requests costs one round trip. A revoked token keeps working for up
# to this long. Rejections are remembered briefly too.
TOKEN_CACHE_SECONDS = 300
REJECTION_CACHE_SECONDS = 30

# Cached in place of an email for a token CourtListener rejects. It is not an
# address, so it can't be mistaken for one.
REJECTED = "!rejected"


class TooManyTokenChecks(Exception):
    """The viewer's address has sent too many tokens the wiki has not seen."""


def cached_verified_email_for(token, request):
    """``verified_email_for``, remembered per token for a few minutes."""
    key = "cl-token:" + hashlib.sha256(token.encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return None if cached == REJECTED else cached
    if ratelimit_token_check(request):
        raise TooManyTokenChecks
    email, ttl = verified_email_for(token)
    cache.set(key, REJECTED if email is None else email, ttl)
    return email


def verified_email_for(token):
    """Who a CourtListener token reads as, and how many seconds that answer
    may be remembered.

    The answer is the account's verified email for a live token carrying the
    ``wiki`` scope; ``""`` (anonymous) for a live token without it, or with no
    verified email behind it; and None for a token CourtListener rejects."""
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
        if not info.get("active"):
            return None, REJECTION_CACHE_SECONDS
        # Never remember a token past its own expiry.
        remaining = int(info.get("exp", 0)) - int(time.time())
        ttl = max(min(TOKEN_CACHE_SECONDS, remaining), 1)
        # Without the scope the user never let the wiki know who they are.
        if "wiki" not in info.get("scope", "").split():
            return "", ttl
        userinfo = cl.get(
            "/o/userinfo/", headers={"Authorization": f"Bearer {token}"}
        )
        # Refused for the token's sake (e.g. no openid scope), not ours.
        if userinfo.status_code in (401, 403):
            return "", ttl
        userinfo.raise_for_status()
    claims = userinfo.json()
    if not (claims.get("email") and claims.get("email_verified")):
        return "", ttl
    return claims["email"].lower(), ttl


def bearer_auth(view):
    """Make ``request.user`` the account behind the request's bearer token.

    A token CourtListener rejects is a 401, and a live one that names no
    account (no ``wiki`` scope, or no verified email) is anonymous.
    CourtListener being unreachable is a 503; too many unseen tokens from one
    address is a 429. Without a token the view sees the request's own
    (session or anonymous) user.
    Responses vary by token, so they are marked uncacheable.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        scheme, _, token = request.headers.get("Authorization", "").partition(
            " "
        )
        if scheme.lower() == "bearer":
            try:
                email = cached_verified_email_for(token.strip(), request)
            except TooManyTokenChecks:
                return JsonResponse({"error": "ratelimited"}, status=429)
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
            user = (
                provision_user(email)
                if email and is_email_allowed(email)
                else None
            )
            if user and user.last_login is None:
                # Count the first use as a sign-in.
                update_last_login(None, user)
            request.user = user or AnonymousUser()
        response = view(request, *args, **kwargs)
        add_never_cache_headers(response)
        return response

    return wrapper
