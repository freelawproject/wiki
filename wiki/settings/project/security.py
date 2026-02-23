import socket

import environ
from csp.constants import SELF

from ..django import DATABASES, INSTALLED_APPS, MIDDLEWARE, TESTING

env = environ.FileAwareEnv()
DEVELOPMENT = env.bool("DEVELOPMENT", default=True)

ALLOWED_HOSTS: list[str] = env(
    "ALLOWED_HOSTS", default=["localhost", "127.0.0.1"]
)

SECURE_HSTS_SECONDS = 63_072_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# CSP: Content Security Policy
# SECURITY: Prevents XSS, clickjacking, and other injection attacks by
# restricting which sources the browser may load resources from.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        # Uses @alpinejs/csp build — no unsafe-eval needed.
        "script-src": [SELF],
        # Needed for style="" HTML attributes in templates.
        "style-src": [SELF, "'unsafe-inline'"],
        "img-src": [
            SELF,
            "https://www.gravatar.com/",
            "data:",
        ],
        "font-src": [SELF],
        "connect-src": [SELF],
        "frame-src": ["'none'"],
        "object-src": ["'none'"],
        "base-uri": [SELF],
    },
}

# Rate limiting: custom 429 handler
RATELIMIT_VIEW = "wiki.lib.views.ratelimited"

if DEVELOPMENT:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_DOMAIN = None
    if not TESTING:
        INSTALLED_APPS.append("debug_toolbar")
        MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS = [".".join(ip.split(".")[:-1] + ["1"]) for ip in ips] + [
        "127.0.0.1"
    ]

    if TESTING:
        db = DATABASES["default"]
        db["ENCODING"] = "UTF8"
        db["TEST_ENCODING"] = "UTF8"
        db["CONN_MAX_AGE"] = 0
        RATELIMIT_ENABLE = False
else:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # SECURITY: In production, allow S3 domain for file serving
    # and force HTTPS for all resources.
    from ..third_party.aws import AWS_S3_CUSTOM_DOMAIN

    s3 = f"https://{AWS_S3_CUSTOM_DOMAIN}/"
    CONTENT_SECURITY_POLICY["DIRECTIVES"]["default-src"].append(s3)
    CONTENT_SECURITY_POLICY["DIRECTIVES"]["img-src"].append(s3)
    CONTENT_SECURITY_POLICY["DIRECTIVES"]["connect-src"].append(s3)
    CONTENT_SECURITY_POLICY["DIRECTIVES"]["upgrade-insecure-requests"] = True
