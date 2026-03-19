"""Backfill FileUpload.page by scanning page and revision content.

Run once after deploying the fix for the orphaned-upload cleanup bug.
Safe to re-run — idempotent.  Scans both current content and all
revisions so that files only referenced by past revisions are also
preserved.
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from wiki.pages.models import FileUpload, Page, PageRevision

FILE_REF_RE = re.compile(r"/files/(\d+)/")


class Command(BaseCommand):
    help = "Link FileUpload records to pages based on /files/<id>/ references in content and revisions."

    def handle(self, *args, **options):
        # Build a map: file_id → first page that references it
        file_to_page = {}
        for page in Page.objects.iterator():
            for fid in FILE_REF_RE.findall(page.content):
                file_to_page.setdefault(int(fid), page)

        for rev in PageRevision.objects.select_related("page").iterator():
            for fid in FILE_REF_RE.findall(rev.content):
                file_to_page.setdefault(int(fid), rev.page)

        if not file_to_page:
            self.stdout.write("No file references found in any content.")
            return

        # Group by page for efficient bulk updates
        page_to_ids = {}
        for fid, page in file_to_page.items():
            page_to_ids.setdefault(page.pk, (page, set()))[1].add(fid)

        linked = 0
        for page, file_ids in page_to_ids.values():
            with transaction.atomic():
                count = FileUpload.objects.filter(
                    id__in=file_ids, page__isnull=True
                ).update(page=page)
            if count:
                self.stdout.write(
                    f"  Linked {count} upload(s) to: {page.title}"
                )
                linked += count

        self.stdout.write(
            self.style.SUCCESS(f"Done. Linked {linked} upload(s) total.")
        )
