"""CourtListener OAuth resource-server settings.

The wiki's read-only JSON API (``wiki/api/``) accepts OAuth2 bearer
tokens minted by CourtListener's authorization server, so the
CourtListener MCP server can read wiki content on behalf of the person
who authorized it. These settings identify that authorization server
and the confidential-client credentials the wiki uses to introspect
tokens against it (RFC 7662). See ``wiki/lib/cl_oauth.py``.
"""

import environ

# Keeps the settings assembly's `import *` from also dragging in `env`.
__all__ = [
    "CL_OAUTH_ISSUER",
    "CL_OAUTH_INTROSPECTION_CLIENT_ID",
    "CL_OAUTH_INTROSPECTION_CLIENT_SECRET",
    "CL_OAUTH_TIMEOUT_SECONDS",
    "CL_TOKEN_CACHE_SECONDS",
]

env = environ.FileAwareEnv()

# Base URL of the CourtListener OAuth2/OIDC authorization server.
CL_OAUTH_ISSUER = env(
    "CL_OAUTH_ISSUER", default="https://www.courtlistener.com"
)

# Credentials of the wiki's confidential client, registered on
# CourtListener as an oauth2_provider Application, used to authenticate
# calls to /o/introspect/. When unset, bearer-token auth is disabled
# and the API serves public content only.
CL_OAUTH_INTROSPECTION_CLIENT_ID = env(
    "CL_OAUTH_INTROSPECTION_CLIENT_ID", default=""
)
CL_OAUTH_INTROSPECTION_CLIENT_SECRET = env(
    "CL_OAUTH_INTROSPECTION_CLIENT_SECRET", default=""
)

# Timeout for introspection/userinfo calls to CourtListener.
CL_OAUTH_TIMEOUT_SECONDS = env.int("CL_OAUTH_TIMEOUT_SECONDS", default=10)

# How long a validated token→user mapping is cached. Bounds both the
# introspection call rate and the revocation propagation delay: a token
# revoked on CourtListener keeps working here for at most this long.
CL_TOKEN_CACHE_SECONDS = env.int("CL_TOKEN_CACHE_SECONDS", default=300)
