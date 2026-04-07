"""Periodic tasks for the pages app, run via cron management commands."""

import io
import logging
from datetime import timedelta

from django.contrib.postgres.search import SearchVector
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from PIL import Image

from .models import FileUpload, Page, PageViewTally

logger = logging.getLogger(__name__)


def sync_page_view_counts():
    """Sum PageViewTally records into Page.view_count and delete tallies.

    Returns the number of pages updated.
    """
    tallies = PageViewTally.objects.values("page_id").annotate(
        total=Sum("count")
    )

    count = 0
    with transaction.atomic():
        for entry in tallies:
            Page.all_objects.filter(id=entry["page_id"]).update(
                view_count=F("view_count") + entry["total"]
            )
            count += 1
        PageViewTally.objects.all().delete()

    return count


def update_search_vectors():
    """Update search_vector for all pages.

    Returns the number of pages updated.
    """
    count = Page.objects.update(
        search_vector=SearchVector("title", weight="A")
        + SearchVector("content", weight="B")
    )
    return count


def purge_deleted_pages(days=90):
    """Permanently delete pages that were soft-deleted more than `days` ago.

    Returns the number of pages purged.
    """
    cutoff = timezone.now() - timedelta(days=days)
    qs = Page.all_objects.filter(is_deleted=True, deleted_at__lte=cutoff)
    count, _ = qs.delete()
    return count


# ── Image optimization ──────────────────────────────────────────────

OPTIMIZABLE_TYPES = {"image/jpeg", "image/png", "image/webp"}
OPTIMIZE_BATCH_SIZE = 50
# Pillow format names keyed by MIME type
_PILLOW_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def _optimize_single_image(upload):
    """Optimize one FileUpload image in-place.

    Returns the number of bytes saved (positive) or the size increase
    (negative) if the optimized version was larger.
    """
    original_bytes = upload.file.read()
    original_size = len(original_bytes)

    img = Image.open(io.BytesIO(original_bytes))
    fmt = _PILLOW_FORMAT[upload.content_type]

    # JPEG cannot store alpha — convert RGBA/P+transparency to RGB
    if fmt == "JPEG" and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    save_kwargs = {"format": fmt, "optimize": True}

    # Preserve ICC color profile if present
    icc_profile = img.info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile

    if fmt == "JPEG":
        save_kwargs["quality"] = 85
    elif fmt == "WEBP":
        save_kwargs["quality"] = 85
        save_kwargs["method"] = 4

    buf = io.BytesIO()
    img.save(buf, **save_kwargs)
    optimized_bytes = buf.getvalue()
    optimized_size = len(optimized_bytes)

    gain = original_size - optimized_size
    if gain <= 0:
        # Optimized version is the same size or larger — keep original
        return gain

    # Replace file in storage at the same key
    storage = upload.file.storage
    name = upload.file.name
    storage.delete(name)
    storage.save(name, ContentFile(optimized_bytes))
    return gain


def optimize_images():
    """Optimize unprocessed image uploads (strip metadata, reduce size).

    Returns the number of images processed.
    """
    uploads = FileUpload.objects.filter(
        optimization_gain__isnull=True,
        content_type__in=OPTIMIZABLE_TYPES,
    )[:OPTIMIZE_BATCH_SIZE]

    count = 0
    for upload in uploads:
        try:
            gain = _optimize_single_image(upload)
            upload.optimization_gain = gain
            upload.save(update_fields=["optimization_gain"])
        except Exception:
            logger.exception("Failed to optimize upload %s", upload.id)
            upload.optimization_gain = 0
            upload.save(update_fields=["optimization_gain"])
        count += 1
    return count
