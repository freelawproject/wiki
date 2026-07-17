"""Resource-server auth: accept CourtListener OAuth2 bearer tokens.

CourtListener runs the OAuth2/OIDC authorization server that the
CourtListener MCP server authenticates its users against. The wiki
accepts those bearer tokens on its JSON API (``wiki/api/``) so MCP
tools can read wiki content *as the person who authorized the MCP
client* — without the wiki running an authorization server of its own.

Trust model (who decides what):

- CourtListener proves *identity*. A presented token is validated with
  RFC 7662 introspection (authenticated with the wiki's confidential
  client credentials), which also enforces the ``wiki:read`` scope the
  user consented to on CourtListener's authorize screen — a token
  minted for the CL API alone doesn't work here (confused-deputy
  guard). The account email then comes from the OIDC userinfo
  endpoint, using the token itself.
- The wiki decides *authorization*. The email is mapped to a wiki
  account through the same allowlist that gates magic-link sign-in,
  and page visibility is enforced downstream by the ordinary
  permission model (``viewable_pages_q`` / ``can_view_page``).
  CourtListener has no say in which pages an account may read.

A valid token whose email is not on the allowlist resolves to
``AnonymousUser`` (public content only) and mints no account row.
Accounts for allowlisted emails are provisioned just-in-time via
``wiki.lib.users.provision_user`` — no prior browser sign-in needed.

Validated token→user mappings are cached (hashed key, never the raw
token) for ``CL_TOKEN_CACHE_SECONDS``, which bounds both the
introspection rate and the revocation propagation delay.
"""

import hashlib
import logging

import httpx
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache

from wiki.lib.access import is_email_allowed
from wiki.lib.users import provision_user

logger = logging.getLogger(__name__)

# Scope a token must carry to be accepted here at all. Defined on the
# CourtListener side (OAUTH2_PROVIDER["SCOPES"]) and requested by the
# MCP server during authorization.
REQUIRED_SCOPE = "wiki:read"

# CL authorization-server endpoints, relative to CL_OAUTH_ISSUER. These
# are advertised in CL's RFC 8414 metadata; hardcoding the well-known
# paths keeps the sketch free of a discovery round-trip.
INTROSPECTION_PATH = "/o/introspect/"
USERINFO_PATH = "/o/userinfo/"

# Cache sentinel for tokens that validated but map to no wiki account
# (not allowlisted, or archived). Caching the miss keeps a burst of
# tool calls from re-introspecting a useless token.
_NO_ACCOUNT = 0


def user_for_bearer_token(raw_token):
    """Resolve an ``Authorization: Bearer`` value to a wiki user.

    Returns a ``User`` for a valid, ``wiki:read``-scoped token whose
    email passes the allowlist; ``AnonymousUser`` otherwise. Invalid
    tokens degrade to anonymous rather than erroring so the API serves
    public content in every case and reveals nothing about why a token
    was rejected (the read endpoint's identical-404 behavior depends on
    this).
    """
    if not raw_token or not settings.CL_OAUTH_INTROSPECTION_CLIENT_ID:
        return AnonymousUser()

    cache_key = _cache_key(raw_token)
    cached = cache.get(cache_key)
    if cached is not None:
        return (
            _user_by_id(cached) if cached != _NO_ACCOUNT else AnonymousUser()
        )

    email = _email_for_token(raw_token)
    if email is None or not is_email_allowed(email):
        cache.set(cache_key, _NO_ACCOUNT, settings.CL_TOKEN_CACHE_SECONDS)
        return AnonymousUser()

    user = provision_user(email)
    if user is None:
        # Archived account: allowlisted, but access has been revoked.
        cache.set(cache_key, _NO_ACCOUNT, settings.CL_TOKEN_CACHE_SECONDS)
        return AnonymousUser()

    cache.set(cache_key, user.id, settings.CL_TOKEN_CACHE_SECONDS)
    return user


def _cache_key(raw_token):
    """Cache key for a token. Hashed so raw tokens never hit storage."""
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    return f"cl-oauth-token:{digest}"


def _user_by_id(user_id):
    """Rehydrate a cached user id, re-checking that it's still active."""
    user = User.objects.filter(pk=user_id, is_active=True).first()
    return user if user is not None else AnonymousUser()


def _email_for_token(raw_token):
    """Validate ``raw_token`` against CourtListener; return its email.

    Two calls: introspection (is the token live, and does it carry
    ``wiki:read``?), then userinfo (whose token is it?). Returns None
    on any failure. CourtListener's userinfo exposes ``email`` /
    ``email_verified`` claims for exactly this hand-off; unverified
    addresses are rejected — an unverified email must not unlock an
    allowlisted identity.
    """
    issuer = settings.CL_OAUTH_ISSUER.rstrip("/")

    introspection = _cl_json(
        "introspection",
        lambda http: http.post(
            f"{issuer}{INTROSPECTION_PATH}",
            data={"token": raw_token},
            auth=(
                settings.CL_OAUTH_INTROSPECTION_CLIENT_ID,
                settings.CL_OAUTH_INTROSPECTION_CLIENT_SECRET,
            ),
        ),
    )
    if not introspection or not introspection.get("active"):
        return None
    if REQUIRED_SCOPE not in (introspection.get("scope") or "").split():
        return None

    userinfo = _cl_json(
        "userinfo",
        lambda http: http.get(
            f"{issuer}{USERINFO_PATH}",
            headers={"Authorization": f"Bearer {raw_token}"},
        ),
    )
    if not userinfo or not userinfo.get("email_verified"):
        return None
    return userinfo.get("email")


def _cl_json(label, make_request):
    """Run an HTTP call against CL, returning parsed JSON or None."""
    try:
        with httpx.Client(timeout=settings.CL_OAUTH_TIMEOUT_SECONDS) as http:
            response = make_request(http)
    except httpx.HTTPError as exc:
        logger.warning("CourtListener %s call failed: %s", label, exc)
        return None
    if response.status_code != 200:
        return None
    return response.json()
