import environ

env = environ.FileAwareEnv()

# All values in seconds.
DAEMON_SYNC_VIEW_COUNTS_INTERVAL = env.int(
    "DAEMON_SYNC_VIEW_COUNTS_INTERVAL", default=5
)
DAEMON_UPDATE_SEARCH_VECTORS_INTERVAL = env.int(
    "DAEMON_UPDATE_SEARCH_VECTORS_INTERVAL", default=30
)
DAEMON_CLEANUP_INTERVAL = env.int(
    "DAEMON_CLEANUP_INTERVAL", default=21600
)  # 6 hours
