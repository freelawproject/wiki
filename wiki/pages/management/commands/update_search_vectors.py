from django.core.management.base import BaseCommand

from wiki.pages.tasks import update_search_vectors


class Command(BaseCommand):
    help = "Update search_vector for all pages."

    def handle(self, *args, **options):
        count = update_search_vectors()
        self.stdout.write(f"Updated search vectors for {count} pages.")
