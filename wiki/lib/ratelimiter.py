"""Rate limit decorators for wiki views.

SECURITY: These decorators prevent abuse of unauthenticated and
resource-intensive endpoints (login, upload, search).

Production sits behind CloudFront, so ``REMOTE_ADDR`` is a CDN edge
address that varies request to request. Counting by it scatters one
client across many buckets (and lumps unrelated clients together), so
every key here counts by CloudFront's ``CloudFront-Viewer-Address``
header instead, the same approach CourtListener uses.
"""

import ipaddress

from django.http import HttpRequest
from django_ratelimit.core import get_header
from django_ratelimit.decorators import ratelimit


def get_viewer_ip(request: HttpRequest) -> str:
    """Return the viewer's address from CloudFront's header.

    CloudFront sends ``IP:port`` with a random port, and IPv6 unbracketed
    (``2600:1f18::1234:51396``), so the port is split off the right.
    Falls back to ``REMOTE_ADDR`` when the header is absent (local
    development, tests) or isn't an address.
    """
    fallback = request.META.get("REMOTE_ADDR", "")
    header = get_header(request, "CloudFront-Viewer-Address")
    if not header:
        return fallback

    address = header.rsplit(":", 1)[0].strip("[]")
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return fallback

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip)


def get_ratelimit_ident(group: str, request: HttpRequest) -> str:
    """Key to count a viewer's requests under: their address.

    An IPv6 address is widened to its /64 — the smallest block a client is
    normally assigned — so rotating within the block can't dodge a limit.
    The ``group`` argument is required by django-ratelimit's callable-key
    signature and unused.
    """
    ip = get_viewer_ip(request)
    if not ip:
        return ""
    if ipaddress.ip_address(ip).version == 4:
        return ip
    return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address)


def get_user_or_ident(group: str, request: HttpRequest) -> str:
    """Key by user id when logged in, otherwise by viewer address."""
    if request.user.is_authenticated:
        return f"user:{request.user.pk}"
    return f"ip:{get_ratelimit_ident(group, request)}"


ratelimit_login = ratelimit(
    key=get_ratelimit_ident, rate="5/m", method=["POST"], block=True
)
ratelimit_upload = ratelimit(
    key=get_user_or_ident, rate="20/m", method=["POST"], block=True
)
ratelimit_search = ratelimit(key=get_user_or_ident, rate="30/m", block=True)
# View tallies are JS-fired from page loads — multiple tabs / prefetches
# from a single IP are normal, so the limit is generous.
ratelimit_view_count = ratelimit(
    key=get_ratelimit_ident, rate="120/m", method=["POST"], block=True
)
# Markdown preview is unauthenticated (anonymous users propose changes and
# preview them) and rendering is CPU-bound, so cap how fast it can be hit.
ratelimit_preview = ratelimit(
    key=get_user_or_ident, rate="30/m", method=["POST"], block=True
)
# Caps how fast a single user can create or move pages. Directory-scoped
# slugs let multiple pages share a name across dirs, so mass-creating
# colliding slugs could force expensive synchronous link-rewrites on
# every existing page that referenced the sibling — the rate limit puts
# an upper bound on the blast radius.
ratelimit_page_write = ratelimit(
    key=get_user_or_ident, rate="30/m", method=["POST"], block=True
)
# The anonymous subscribe form sends email to an arbitrary address, so
# it's a spam vector; keep it tight per-IP with a daily backstop
# (django_ratelimit decorators stack).
ratelimit_email_subscribe = ratelimit(
    key=get_ratelimit_ident, rate="5/m", method=["POST"], block=True
)
ratelimit_email_subscribe_daily = ratelimit(
    key=get_ratelimit_ident, rate="20/d", method=["POST"], block=True
)
# Anonymous visitors can comment and propose page changes through the
# feedback form, which is the scanner/spam entry point. A human makes a
# handful of submissions a minute at most, so stack minute, hour and day
# caps (django_ratelimit decorators stack).
ratelimit_feedback = ratelimit(
    key=get_user_or_ident, rate="5/m", method=["POST"], block=True
)
ratelimit_feedback_hourly = ratelimit(
    key=get_user_or_ident, rate="20/h", method=["POST"], block=True
)
ratelimit_feedback_daily = ratelimit(
    key=get_user_or_ident, rate="20/d", method=["POST"], block=True
)

# Site-wide ceilings on state-changing requests per viewer, enforced by
# ``GlobalWriteRateLimitMiddleware`` so new views are covered by default.
# Twice the feedback caps, to leave room for the other kinds of writes a
# real person mixes in. The tighter per-view limits above still apply.
GLOBAL_WRITE_RATES = ("10/m", "40/h")
