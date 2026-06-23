"""Serialize JSON for safe embedding inside an HTML ``<script>`` block.

``json.dumps`` leaves ``<``, ``>`` and ``&`` intact, so a ``</script>``
substring in any serialized value (e.g. a user-supplied page or directory
title) would close the surrounding ``<script>`` element early and allow stored
XSS. Escape those characters as ``\\uXXXX`` sequences — the same set Django's
``json_script()`` uses. We can't use ``json_script()`` directly because it
hardcodes ``type="application/json"`` (crawlers don't parse that as JSON-LD)
and wraps its own tag, and its escape table isn't public. The browser's JSON
parser decodes the sequences back to the original characters, so the embedded
data stays correct.
"""

import json

# chr(92) is the backslash; building the escapes this way keeps the source free
# of literal backslashes (and the escaping bugs that come with them).
_SCRIPT_ESCAPES = {ord(c): chr(92) + f"u{ord(c):04x}" for c in "<>&"}


def dump_json_for_script(value) -> str:
    """Serialize ``value`` to a JSON string safe to embed in a ``<script>``."""
    return json.dumps(value).translate(_SCRIPT_ESCAPES)
