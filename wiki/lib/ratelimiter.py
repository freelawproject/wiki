"""Rate limit decorators for wiki views.

SECURITY: These decorators prevent abuse of unauthenticated and
resource-intensive endpoints (login, upload, search).
"""

from django_ratelimit.decorators import ratelimit

ratelimit_login = ratelimit(
    key="ip", rate="5/m", method=["POST"], block=True
)
ratelimit_upload = ratelimit(
    key="user_or_ip", rate="20/m", method=["POST"], block=True
)
ratelimit_search = ratelimit(
    key="user_or_ip", rate="30/m", block=True
)
