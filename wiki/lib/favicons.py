"""Fetch and normalize favicons for allowlisted domains.

Domain-access badges show a granting domain's favicon next to content shared
with it. The browser can't load an external favicon directly (the CSP limits
``img-src`` to ``self``/Gravatar/``data:``/S3), so we fetch each domain's
favicon server-side, normalize it to a small PNG, and serve it from our own
host.

Fetching reaches out to admin-supplied domains, so it is hardened against SSRF:
https-only; the host is resolved once and must resolve entirely to public IPs,
and we connect to that pinned IP so a DNS rebind can't swap in a private target
between the check and the connect (redirects are bounded and re-validated per
hop); short timeout; capped read size; a decoded-pixel cap against
decompression bombs; and Pillow rasterization (so we never store or serve
SVG/script payloads). All failures are swallowed — a missing favicon just
yields the fallback icon in the UI.
"""

import http.client
import io
import ipaddress
import logging
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from django.utils import timezone
from PIL import Image

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 5  # seconds
MAX_HTML_BYTES = 512_000  # homepage read cap while hunting for <link rel=icon>
MAX_ICON_BYTES = 256_000  # favicon read cap
FAVICON_SIZE = 32  # px; normalized square output
MAX_REDIRECTS = 3  # bounded, and each hop is re-resolved + IP-pinned
# A favicon source is small; cap decoded pixels so a "decompression bomb"
# (tiny compressed file declaring a huge bitmap) can't OOM the daemon. Pillow's
# own DecompressionBombError only fires above 2x its ~89M default, so we guard
# explicitly on declared dimensions before decoding.
MAX_DECODED_PIXELS = 2_000_000  # ~1414x1414; generous for a favicon source
_UA = "FLPWiki-favicon-fetcher/1.0"

# Defense in depth: also lower Pillow's global bomb threshold.
Image.MAX_IMAGE_PIXELS = MAX_DECODED_PIXELS


def _ip_is_public(ip):
    """True unless ``ip`` is loopback/private/link-local/reserved/etc."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_public_ip(host, port):
    """Resolve ``host`` once and return a single IP to connect to — but only
    if EVERY resolved address is publicly routable; otherwise None.

    Returning the address (rather than a bool) lets the caller connect to that
    exact IP, so the address we validated is the address we connect to. That
    closes the DNS-rebinding TOCTOU where a second, unvalidated resolution at
    connect time could land on a private/loopback target. Fails closed on a
    resolution error or an empty result.
    """
    if not host:
        return None
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    if not infos:
        return None
    for info in infos:
        if not _ip_is_public(ipaddress.ip_address(info[4][0])):
            return None
    return infos[0][4][0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection to a pre-validated IP, keeping the original hostname
    for SNI and certificate verification — so the address we vetted is the one
    we connect to (no rebinding window)."""

    def __init__(self, host, pinned_ip, *, port, timeout, context):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _fetch(url, max_bytes):
    """GET ``url`` over HTTPS and return up to ``max_bytes`` of the body.

    https-only; the host is resolved once and must be entirely public, and we
    connect to that pinned IP (no DNS-rebinding TOCTOU). Redirects are followed
    up to ``MAX_REDIRECTS``, each hop independently re-resolved, re-validated,
    and re-pinned. Raises on any refusal, oversize body, or too many redirects.
    """
    redirects = 0
    while True:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"refusing non-https url: {url}")
        host = parsed.hostname
        port = parsed.port or 443
        ip = _resolve_public_ip(host, port)
        if ip is None:
            raise ValueError(f"refusing non-public/unresolvable host: {host}")
        conn = _PinnedHTTPSConnection(
            host,
            ip,
            port=port,
            timeout=FETCH_TIMEOUT,
            context=ssl.create_default_context(),
        )
        try:
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            conn.request("GET", path, headers={"User-Agent": _UA})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise ValueError(f"redirect without Location from {url}")
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    raise ValueError(f"too many redirects from {url}")
                url = urljoin(url, location)
                continue
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(
                    f"response from {url} exceeds {max_bytes} bytes"
                )
            return body
        finally:
            conn.close()


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
        # Reject decompression bombs by declared size *before* decoding —
        # Image.open only reads the header, so img.size is known without
        # allocating the full bitmap.
        w, h = img.size
        if w * h > MAX_DECODED_PIXELS:
            return None
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
    allowed_domain.save(update_fields=["favicon_data", "favicon_checked_at"])
