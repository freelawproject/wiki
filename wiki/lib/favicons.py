"""Fetch and normalize favicons for allowlisted domains.

Domain-access badges show a granting domain's favicon next to content shared
with it. The browser can't load an external favicon directly (the CSP limits
``img-src`` to ``self``/Gravatar/``data:``/S3), so we fetch each domain's
favicon server-side, normalize it to a small PNG, and serve it from our own
host.

Fetching reaches out to admin-supplied domains, so it is hardened against SSRF:
https-only, public-IP-only (re-checked on redirects), short timeout, capped
read size, and Pillow rasterization (so we never store or serve SVG/script
payloads). All failures are swallowed — a missing favicon just yields the
fallback icon in the UI.
"""

import io
import ipaddress
import logging
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.utils import timezone
from PIL import Image

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 5  # seconds
MAX_HTML_BYTES = 512_000  # homepage read cap while hunting for <link rel=icon>
MAX_ICON_BYTES = 256_000  # favicon read cap
FAVICON_SIZE = 32  # px; normalized square output
_UA = "FLPWiki-favicon-fetcher/1.0"


def _host_is_public(host):
    """True only if every address ``host`` resolves to is publicly routable.

    Blocks SSRF to loopback/private/link-local/reserved ranges (e.g. a domain
    whose DNS points at 127.0.0.1 or 169.254.169.254).
    """
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Re-validate the scheme/host on every redirect hop (SSRF defense)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or not _host_is_public(parsed.hostname):
            return None  # stop following; do not chase to an unsafe target
        return super().redirect_request(
            req, fp, code, msg, headers, newurl
        )


_opener = build_opener(_SafeRedirectHandler())


def _fetch(url, max_bytes):
    """GET ``url`` (https + public host only) and return up to ``max_bytes``.

    Raises on any failure, unsafe target, or oversize response.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refusing non-https url: {url}")
    if not _host_is_public(parsed.hostname):
        raise ValueError(f"refusing non-public host: {parsed.hostname}")
    req = Request(url, headers={"User-Agent": _UA})
    resp = _opener.open(req, timeout=FETCH_TIMEOUT)  # noqa: S310
    body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"response from {url} exceeds {max_bytes} bytes")
    return body


class _IconLinkParser(HTMLParser):
    """Pull the first ``<link rel=...icon...>`` href out of a homepage."""

    def __init__(self):
        super().__init__()
        self.icon_href = None

    def handle_starttag(self, tag, attrs):
        if tag != "link" or self.icon_href:
            return
        d = {k.lower(): (v or "") for k, v in attrs}
        rel = d.get("rel", "").lower().split()
        if "icon" in rel and d.get("href"):
            self.icon_href = d["href"]


def _rasterize_to_png(raw):
    """Normalize arbitrary image bytes to a small square PNG, or None.

    Pillow handles ICO/PNG/GIF/JPEG/BMP; SVG and anything unparseable return
    None (caller falls back). Rasterizing also strips any active content.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGBA")
        img.thumbnail((FAVICON_SIZE, FAVICON_SIZE))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return None


def fetch_favicon(domain):
    """Return normalized PNG bytes for ``domain``'s favicon, or None.

    Tries the homepage's ``<link rel=icon>`` first, then ``/favicon.ico``.
    Never raises — any failure yields None.
    """
    domain = (domain or "").strip().lower().lstrip("@").strip(".")
    if not domain:
        return None
    base = f"https://{domain}/"

    candidates = []
    try:
        html = _fetch(base, MAX_HTML_BYTES)
        parser = _IconLinkParser()
        parser.feed(html.decode("utf-8", errors="ignore"))
        if parser.icon_href:
            candidates.append(urljoin(base, parser.icon_href))
    except Exception:
        logger.debug("favicon: homepage fetch failed for %s", domain)
    candidates.append(urljoin(base, "/favicon.ico"))

    for url in candidates:
        try:
            png = _rasterize_to_png(_fetch(url, MAX_ICON_BYTES))
        except Exception:
            continue
        if png:
            return png
    return None


def store_favicon(allowed_domain):
    """Fetch ``allowed_domain``'s favicon and persist it. Best-effort.

    Always stamps ``favicon_checked_at`` (so the daemon backs off), and sets
    ``favicon_data`` to the PNG bytes or None. Swallows all errors.
    """
    try:
        data = fetch_favicon(allowed_domain.domain)
    except Exception:
        logger.warning(
            "favicon: unexpected error fetching %s",
            allowed_domain.domain,
            exc_info=True,
        )
        data = None
    allowed_domain.favicon_data = data
    allowed_domain.favicon_checked_at = timezone.now()
    allowed_domain.save(
        update_fields=["favicon_data", "favicon_checked_at"]
    )
