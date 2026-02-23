import sys

import environ

env = environ.FileAwareEnv()

TESTING = "test" in sys.argv
if TESTING:
    DEBUG = env.bool("TESTING_DEBUG", default=False)
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]
