"""Generate alt text for uploaded images via the Anthropic API.

Called synchronously from the upload views so the markdown snippet
returned to the editor already carries a useful description instead of
the filename. Failures of any kind (no API key, unsupported type,
oversized image, API errors, timeouts) return ``None`` and the caller
falls back to the current filename-as-alt behavior — an upload must
never fail or block on the AI call.
"""

import base64
import json
import logging

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)

# Image types the Anthropic API accepts as input. Mirrored by
# AI_ALT_TYPES in wiki/assets/static-global/js/markdown-editor.js.
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

# The API caps images at 5 MB; stay under it with margin for base64.
MAX_IMAGE_BYTES = int(4.5 * 1024 * 1024)

# The call runs inside the upload request, so keep it bounded: one
# attempt, and give up well before the browser or proxy would.
REQUEST_TIMEOUT_SECONDS = 30.0

_PROMPT = (
    "Write alt text for this image, uploaded to an organizational wiki. "
    "One concise sentence (under 125 characters) describing what the "
    "image shows, suitable for screen readers. Include important visible "
    "text such as headings, labels, or error messages so the description "
    "is also useful for search. Don't start with 'Image of' or "
    "'Screenshot of' unless the medium matters."
)

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"alt_text": {"type": "string"}},
        "required": ["alt_text"],
        "additionalProperties": False,
    },
}


def describe_image(image_bytes, content_type):
    """Return AI-generated alt text for an image, or None to skip.

    None means "use the fallback" — the feature is disabled, the image
    can't be sent to the API, or the call failed.
    """
    if not settings.ANTHROPIC_API_KEY:
        return None
    if content_type not in SUPPORTED_IMAGE_TYPES:
        return None
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return None

    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    try:
        response = client.messages.create(
            model=settings.ANTHROPIC_OCR_MODEL,
            max_tokens=1024,
            output_config={"effort": "low", "format": _OUTPUT_SCHEMA},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": content_type,
                                "data": base64.standard_b64encode(
                                    image_bytes
                                ).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
    except anthropic.APIError:
        logger.warning("Alt text generation failed", exc_info=True)
        return None

    if response.stop_reason != "end_turn":
        # Refusal or truncation — structured output isn't guaranteed.
        logger.warning(
            "Alt text generation stopped early: %s", response.stop_reason
        )
        return None

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        alt_text = json.loads(text)["alt_text"].strip()
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
        # TypeError covers valid JSON that isn't an object (e.g. a bare
        # list or number) — the schema forbids it, but don't bet on that.
        logger.warning("Alt text response was not valid JSON: %r", text[:200])
        return None
    return alt_text or None
