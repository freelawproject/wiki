"""Replace tab characters in stored markdown with spaces.

``Page.save()`` and ``Directory.save()`` expand tabs on every save, but
only for content saved after that behaviour shipped. Run this once to
bring the pages and directory descriptions saved before it into line.
Tabs inside fenced code blocks are left alone (see
``wiki.lib.markdown_source.expand_tabs``). Idempotent: a second run finds
nothing to change.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from wiki.directories.models import Directory
from wiki.lib.markdown_source import expand_tabs
from wiki.pages.models import Page

CHANGE_MESSAGE = "Replace tabs with spaces"


class Command(BaseCommand):
    help = (
        "Replace tab characters in page content and directory descriptions "
        "with spaces, recording a revision for each changed item."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would change without saving anything.",
        )

    def handle(self, *args, dry_run, **options):
        pages = self._expand(
            Page.objects.filter(content__contains="\t"),
            "content",
            dry_run,
        )
        directories = self._expand(
            Directory.objects.filter(description__contains="\t"),
            "description",
            dry_run,
        )
        summary = (
            f"{pages} {'page' if pages == 1 else 'pages'} and "
            f"{directories} "
            f"{'directory' if directories == 1 else 'directories'}"
        )
        if dry_run:
            self.stdout.write(f"{summary} would be rewritten.")
            return
        self.stdout.write(self.style.SUCCESS(f"Rewrote {summary}."))

    def _expand(self, queryset, field, dry_run):
        """Expand tabs in ``field`` of every object in ``queryset``.

        Returns the number of objects that changed (or would change).
        """
        changed = 0
        for obj in queryset.order_by("pk").iterator():
            old = getattr(obj, field)
            new = expand_tabs(old)
            if new == old:
                # Only tabs inside fenced code blocks: nothing to do.
                continue
            changed += 1
            verb = "Would rewrite" if dry_run else "Rewrote"
            self.stdout.write(f"{verb} {obj.get_absolute_url()}")
            if dry_run:
                continue
            setattr(obj, field, new)
            # The content update and its revision row must succeed or fail
            # together, or history loses track of why the content changed.
            with transaction.atomic():
                obj.save(update_fields=[field, "updated_at"])
                obj.create_revision(None, CHANGE_MESSAGE)
        return changed
