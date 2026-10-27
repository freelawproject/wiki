import environ

env = environ.FileAwareEnv()

# The OAuth server whose bearer tokens the JSON API accepts, and this wiki's
# confidential client there, used to introspect those tokens.
COURTLISTENER_URL = env(
    "COURTLISTENER_URL", default="https://www.courtlistener.com"
)
COURTLISTENER_CLIENT_ID = env("COURTLISTENER_CLIENT_ID", default="")
COURTLISTENER_CLIENT_SECRET = env("COURTLISTENER_CLIENT_SECRET", default="")
