from django.core.management.base import BaseCommand

from wiki.pages.tasks import sync_page_view_counts


class Command(BaseCommand):
    help = "Sum PageViewTally records into Page.view_count and delete tallies."

    def handle(self, *args, **options):
        count = sync_page_view_counts()
        self.stdout.write(f"Synced view counts for {count} pages.")
