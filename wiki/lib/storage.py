from storages.backends.s3boto3 import S3Boto3Storage, S3ManifestStaticStorage


class SubDirectoryS3ManifestStaticStorage(S3ManifestStaticStorage):
    location = "static"


class PrivateS3Storage(S3Boto3Storage):
    """S3 storage for private file uploads (wiki page attachments)."""

    default_acl = "private"
    querystring_auth = True
    querystring_expire = 300  # 5-minute signed URLs

    def __init__(self, **kwargs):
        from django.conf import settings

        kwargs.setdefault(
            "bucket_name", settings.AWS_PRIVATE_STORAGE_BUCKET_NAME
        )
        super().__init__(**kwargs)
