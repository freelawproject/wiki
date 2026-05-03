"""Rate limit decorators for wiki views.

SECURITY: These decorators prevent abuse of unauthenticated and
resource-intensive endpoints (login, upload, search).
"""

from django_ratelimit.decorators import ratelimit

ratelimit_login = ratelimit(key="ip", rate="5/m", method=["POST"], block=True)
ratelimit_upload = ratelimit(
    key="user_or_ip", rate="20/m", method=["POST"], block=True
)
ratelimit_search = ratelimit(key="user_or_ip", rate="30/m", block=True)
# View tallies are JS-fired from page loads — multiple tabs / prefetches
# from a single IP are normal, so the limit is generous.
ratelimit_view_count = ratelimit(
    key="ip", rate="120/m", method=["POST"], block=True
)
# Caps how fast a single user can create or move pages. Directory-scoped
# slugs let multiple pages share a name across dirs, so mass-creating
# colliding slugs could force expensive synchronous link-rewrites on
# every existing page that referenced the sibling — the rate limit puts
# an upper bound on the blast radius.
ratelimit_page_write = ratelimit(
    key="user_or_ip", rate="30/m", method=["POST"], block=True
)
