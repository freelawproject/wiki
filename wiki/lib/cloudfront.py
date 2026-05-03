import logging
import uuid
from collections.abc import Iterable

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_client():
    return boto3.client(
        "cloudfront",
        # CloudFront is global; its control plane lives in us-east-1.
        # Pin the region so this works in containers without
        # AWS_DEFAULT_REGION (otherwise calls fail silently — errors
        # are swallowed by ``invalidate_paths`` to keep writes from
        # rolling back over a CDN issue).
        region_name="us-east-1",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


# CloudFront caps a single invalidation batch at 3,000 paths.
_MAX_BATCH = 3000


def _normalize(path: str) -> str:
    # CloudFront keys exclude query strings and fragments by default,
    # so an invalidation against ``/c/foo?bar=1`` would burn a slot for
    # nothing. Strip both before sending.
    path = path.split("?", 1)[0].split("#", 1)[0]
    return path if path.startswith("/") else f"/{path}"


def invalidate_paths(paths: Iterable[str]) -> None:
    """Submit a CloudFront invalidation for the given paths.

    No-ops when ``CLOUDFRONT_DISTRIBUTION_ID`` is unset (dev / staging
    without a CDN). Errors from boto3 are logged and swallowed: an
    invalidation failure must not break the surrounding write.
    """
    distribution_id = settings.CLOUDFRONT_DISTRIBUTION_ID
    if not distribution_id:
        return

    unique_paths = sorted({_normalize(p) for p in paths if p})
    if not unique_paths:
        return

    client = _get_client()
    for i in range(0, len(unique_paths), _MAX_BATCH):
        chunk = unique_paths[i : i + _MAX_BATCH]
        try:
            client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    "Paths": {
                        "Quantity": len(chunk),
                        "Items": chunk,
                    },
                    "CallerReference": str(uuid.uuid4()),
                },
            )
        except (BotoCoreError, ClientError):
            logger.exception(
                "CloudFront invalidation failed for paths=%s", chunk
            )
