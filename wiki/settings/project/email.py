import environ

env = environ.FileAwareEnv()
DEVELOPMENT = env.bool("DEVELOPMENT", default=True)

if DEVELOPMENT:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django_ses.SESBackend"
    AWS_SES_REGION_NAME = "us-west-2"
    AWS_SES_REGION_ENDPOINT = "email.us-west-2.amazonaws.com"

SERVER_EMAIL = "FLP Wiki <noreply@free.law>"
DEFAULT_FROM_EMAIL = "FLP Wiki <noreply@free.law>"

# Magic link expiry in minutes
MAGIC_LINK_EXPIRY_MINUTES = 15

# Base URL for links in emails and console output.
# In dev this should match the *host* port from docker-compose.
BASE_URL = env("BASE_URL", default="http://localhost:8001")
