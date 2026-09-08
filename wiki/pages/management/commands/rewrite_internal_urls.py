"""Rewrite page URLs in existing content to ``#dir/slug`` wiki links.

``Page.save()`` converts pasted page URLs to wiki links on every save, but
only for content saved after that behaviour shipped. Run this once to
bring the pages saved before it into line. Idempotent: a second run finds
nothing to change.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from wiki.lib.markdown import internal_urls_to_wiki_links
from wiki.pages.models import Page

CHANGE_MESSAGE = "Rewrite page URLs as wiki links"


class Command(BaseCommand):
    help = "Rewrite page URLs in existing page content to #dir/slug wiki links."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the pages that would change without saving anything.",
        )

    def handle(self, *args, dry_run, **options):
        # Only content that can contain a page URL is worth parsing.
        pages = (
            Page.objects.filter(content__contains="/c/")
            .select_related("directory")
            .order_by("pk")
        )
        changed = 0
        for page in pages.iterator():
            new_content = internal_urls_to_wiki_links(page.content)
            if new_content == page.content:
                continue
            changed += 1
            verb = "Would rewrite" if dry_run else "Rewrote"
            self.stdout.write(f"{verb} {page.get_absolute_url()}")
            if dry_run:
                continue
            page.content = new_content
            # The content update and its revision row must succeed or fail
            # together, or history loses track of why the content changed.
            with transaction.atomic():
                page.save(update_fields=["content", "updated_at"])
                page.create_revision(user=None, change_message=CHANGE_MESSAGE)

        noun = "page" if changed == 1 else "pages"
        if dry_run:
            self.stdout.write(f"{changed} {noun} would be rewritten.")
            return
        self.stdout.write(self.style.SUCCESS(f"Rewrote {changed} {noun}."))
