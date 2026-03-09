import boto3
from storages.backends.s3boto3 import S3Boto3Storage, S3ManifestStaticStorage


def get_s3_client():
    """Return a boto3 S3 client configured with project credentials."""
    from django.conf import settings

    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


class SubDirectoryS3ManifestStaticStorage(S3ManifestStaticStorage):
    location = "static"


class PrivateS3Storage(S3Boto3Storage):
    """S3 storage for private file uploads (wiki page attachments)."""

    default_acl = "private"
    custom_domain = (
        None  # Override global AWS_S3_CUSTOM_DOMAIN so urls are signed
    )
    querystring_auth = True
    querystring_expire = 300  # 5-minute signed URLs

    def __init__(self, **kwargs):
        from django.conf import settings

        kwargs.setdefault(
            "bucket_name", settings.AWS_PRIVATE_STORAGE_BUCKET_NAME
        )
        super().__init__(**kwargs)
