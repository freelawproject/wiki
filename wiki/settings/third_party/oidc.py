import environ

__all__ = [
    "AUTHENTICATION_BACKENDS",
    "COURTLISTENER_LOGIN_ENABLED",
    "COURTLISTENER_OIDC_ISSUER",
    "OIDC_OP_AUTHORIZATION_ENDPOINT",
    "OIDC_OP_JWKS_ENDPOINT",
    "OIDC_OP_TOKEN_ENDPOINT",
    "OIDC_OP_USER_ENDPOINT",
    "OIDC_RP_CLIENT_ID",
    "OIDC_RP_CLIENT_SECRET",
    "OIDC_RP_SCOPES",
    "OIDC_RP_SIGN_ALGO",
    "OIDC_TIMEOUT",
    "OIDC_TOKEN_USE_BASIC_AUTH",
    "OIDC_USE_PKCE",
]

env = environ.FileAwareEnv()

# "Sign in with CourtListener". Disabled until a client is registered there
# and its credentials are set.
COURTLISTENER_OIDC_ISSUER = env(
    "COURTLISTENER_OIDC_ISSUER", default="https://www.courtlistener.com"
).rstrip("/")
# Server-to-server calls (token, userinfo, JWKS) may need a different host
# than the browser does, e.g. host.docker.internal in dev.
_INTERNAL_ISSUER = env(
    "COURTLISTENER_OIDC_INTERNAL_ISSUER", default=COURTLISTENER_OIDC_ISSUER
).rstrip("/")
OIDC_RP_CLIENT_ID = env("COURTLISTENER_OIDC_CLIENT_ID", default="")
OIDC_RP_CLIENT_SECRET = env("COURTLISTENER_OIDC_CLIENT_SECRET", default="")
COURTLISTENER_LOGIN_ENABLED = bool(OIDC_RP_CLIENT_ID and OIDC_RP_CLIENT_SECRET)

OIDC_OP_AUTHORIZATION_ENDPOINT = f"{COURTLISTENER_OIDC_ISSUER}/o/authorize/"
OIDC_OP_TOKEN_ENDPOINT = f"{_INTERNAL_ISSUER}/o/token/"
OIDC_OP_USER_ENDPOINT = f"{_INTERNAL_ISSUER}/o/userinfo/"
OIDC_OP_JWKS_ENDPOINT = f"{_INTERNAL_ISSUER}/o/.well-known/jwks.json"
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid email profile"
OIDC_USE_PKCE = True
OIDC_TOKEN_USE_BASIC_AUTH = True
OIDC_TIMEOUT = 10

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "wiki.users.auth.CourtListenerOIDCBackend",
]
