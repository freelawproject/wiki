"""Periodic cleanup: expired sessions, magic tokens, orphaned uploads."""

from datetime import timedelta

from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from wiki.pages.models import FileUpload, PendingUpload
from wiki.users.models import UserProfile


class Command(BaseCommand):
    help = "Clean up expired sessions, magic tokens, and orphaned uploads."

    def handle(self, *args, **options):
        now = timezone.now()
        self._clear_expired_sessions(now)
        self._clear_expired_magic_tokens(now)
        self._delete_orphaned_uploads(now)
        self._delete_stale_pending_uploads(now)
        self._clear_expired_edit_locks()

    def _clear_expired_sessions(self, now):
        count, _ = Session.objects.filter(expire_date__lt=now).delete()
        self.stdout.write(f"Deleted {count} expired session(s).")

    def _clear_expired_magic_tokens(self, now):
        count = (
            UserProfile.objects.filter(
                magic_link_expires__lt=now,
            )
            .exclude(
                magic_link_token="",
            )
            .update(
                magic_link_token="",
                magic_link_expires=None,
            )
        )
        self.stdout.write(f"Cleared {count} expired magic token(s).")

    def _delete_orphaned_uploads(self, now):
        cutoff = now - timedelta(hours=24)
        orphans = FileUpload.objects.filter(
            page__isnull=True,
            created_at__lt=cutoff,
        )
        count = 0
        for upload in orphans:
            upload.file.delete(save=False)
            upload.delete()
            count += 1
        self.stdout.write(f"Deleted {count} orphaned upload(s).")

    def _delete_stale_pending_uploads(self, now):
        cutoff = now - timedelta(hours=2)
        stale = PendingUpload.objects.filter(created_at__lt=cutoff)
        count = 0
        for pending in stale:
            # Try to clean up the S3 object if it exists
            try:
                from django.conf import settings

                from wiki.lib.storage import get_s3_client

                client = get_s3_client()
                client.delete_object(
                    Bucket=settings.AWS_PRIVATE_STORAGE_BUCKET_NAME,
                    Key=pending.s3_key,
                )
            except Exception:
                pass  # Best effort; object may not exist
            pending.delete()
            count += 1
        self.stdout.write(f"Deleted {count} stale pending upload(s).")

    def _clear_expired_edit_locks(self):
        from wiki.lib.edit_lock import cleanup_expired_locks

        count = cleanup_expired_locks()
        self.stdout.write(f"Deleted {count} expired edit lock(s).")
