"""Fetch JSON from external APIs and substitute values into page content.

Pages can configure a data_source_url. When rendered, the URL is fetched,
the JSON response is cached in memory, and [[ key ]] placeholders in the
markdown are replaced with values from the JSON object.

Caching uses a stale-while-error strategy: fresh data is served for `ttl`
seconds, and stale data is served for up to 3x `ttl` if a refetch fails.
"""

import json
import logging
import re
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

# In-memory cache: url -> {"data": dict, "fetched_at": float, "ttl": int}
_cache = {}
_cache_lock = threading.Lock()

# Matches [[ key ]] or [[ nested.key ]] placeholders
DATA_VAR_RE = re.compile(r"\[\[\s*([\w.]+)\s*\]\]")

# Protect fenced code blocks and inline code from substitution
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")

# Safety limits
MAX_RESPONSE_BYTES = 102_400  # 100 KB
FETCH_TIMEOUT = 5  # seconds


def is_domain_allowed(url):
    """Check whether *url*'s domain is in the allowlist."""
    allowed = getattr(settings, "DATA_SOURCE_ALLOWED_DOMAINS", [])
    if not allowed:
        return True
    hostname = urlparse(url).hostname or ""
    return hostname in allowed


def fetch_page_data(url, ttl=300):
    """Fetch JSON data from *url* with in-memory caching.

    - Fresh (age < ttl): return cached data immediately.
    - Stale (ttl <= age < 3*ttl): attempt refetch; on failure return stale.
    - Expired (age >= 3*ttl) or uncached: fetch; on failure return {}.
    """
    if not is_domain_allowed(url):
        logger.warning("Data source domain not in allowlist: %s", url)
        return {}

    now = time.monotonic()

    with _cache_lock:
        entry = _cache.get(url)

    if entry:
        age = now - entry["fetched_at"]
        if age < ttl:
            return entry["data"]
        # Stale but within grace period — try refetch with fallback
        if age < ttl * 3:
            try:
                data = _do_fetch(url)
            except Exception:
                logger.warning(
                    "Data source fetch failed for %s, serving stale cache",
                    url,
                )
                return entry["data"]
            with _cache_lock:
                _cache[url] = {
                    "data": data,
                    "fetched_at": now,
                    "ttl": ttl,
                }
            return data

    # No cache or expired beyond grace period
    try:
        data = _do_fetch(url)
    except Exception:
        logger.warning("Data source fetch failed for %s", url, exc_info=True)
        return {}
    with _cache_lock:
        _cache[url] = {"data": data, "fetched_at": now, "ttl": ttl}
    return data


def _do_fetch(url):
    """GET *url* and return parsed JSON. Raises on any failure."""
    req = Request(url, headers={"Accept": "application/json"})
    resp = urlopen(req, timeout=FETCH_TIMEOUT)  # noqa: S310
    body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Response from {url} exceeds 100 KB limit")
    return json.loads(body)


def substitute_data_variables(content, data):
    """Replace ``[[ key ]]`` placeholders with values from *data*.

    Supports dot-notation for nested dicts: ``[[ stats.total ]]``.
    Placeholders inside fenced or inline code blocks are not touched.
    Unresolved placeholders are left as-is.
    """
    if not data:
        return content

    # Protect code regions from substitution
    protected = {}
    counter = 0

    def _protect(match):
        nonlocal counter
        key = f"\x00PROTECTED{counter}\x00"
        counter += 1
        protected[key] = match.group(0)
        return key

    content = _FENCED_CODE_RE.sub(_protect, content)
    content = _INLINE_CODE_RE.sub(_protect, content)

    def _replace(match):
        key_path = match.group(1)
        value = data
        for part in key_path.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return match.group(0)  # leave as-is
        if value is None:
            return match.group(0)
        return str(value)

    content = DATA_VAR_RE.sub(_replace, content)

    # Restore protected regions
    for key, original in protected.items():
        content = content.replace(key, original)

    return content


def clear_cache():
    """Clear the in-memory data source cache (useful for tests)."""
    with _cache_lock:
        _cache.clear()
