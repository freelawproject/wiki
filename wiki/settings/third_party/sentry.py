import environ
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

env = environ.FileAwareEnv()
SENTRY_DSN = env("SENTRY_DSN", default="")
GIT_SHA = env("GIT_SHA", default="")

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        release=GIT_SHA or None,
        integrations=[
            DjangoIntegration(),
        ],
        ignore_errors=[KeyboardInterrupt],
        attach_stacktrace=True,
    )
