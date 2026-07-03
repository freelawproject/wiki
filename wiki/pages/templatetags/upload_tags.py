"""Template tags for the file-upload editor config."""

from django import template
from django.utils.safestring import mark_safe

from wiki.lib.safe_json import dump_json_for_script
from wiki.pages.ocr import SUPPORTED_IMAGE_TYPES

register = template.Library()


@register.simple_tag
def ai_image_types():
    """JSON array of image MIME types the server describes with AI.

    Rendered into the editor-config block so the editor's upload status
    text stays in sync with ``SUPPORTED_IMAGE_TYPES`` — the single
    source of truth for which uploads get an alt-text pass.
    """
    return mark_safe(dump_json_for_script(sorted(SUPPORTED_IMAGE_TYPES)))
