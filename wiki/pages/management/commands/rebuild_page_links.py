"""Rebuild the PageLink table from current page content.

Run this once after adding the PageLink model to backfill links
for existing pages.
"""

from django.core.management.base import BaseCommand

from wiki.pages.models import Page


class Command(BaseCommand):
    help = "Rebuild all PageLink rows from current page content."

    def handle(self, *args, **options):
        pages = Page.objects.all()
        count = pages.count()
        for i, page in enumerate(pages.iterator(), 1):
            page._update_page_links()
            if i % 100 == 0:
                self.stdout.write(f"  Processed {i}/{count} pages...")
        self.stdout.write(
            self.style.SUCCESS(f"Rebuilt links for {count} pages.")
        )
