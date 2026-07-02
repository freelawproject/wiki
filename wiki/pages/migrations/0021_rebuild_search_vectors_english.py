"""Rebuild search vectors with an explicit english config.

Vectors were previously built with the server's default_text_search_config,
which varies by environment (e.g. "simple" on some CI/production images and
no stemming as a result). Now that SearchVector/SearchQuery pin
config="english", rebuild stored vectors so they match at query time.
"""

from django.contrib.postgres.search import SearchVector
from django.db import migrations

SEARCH_CONFIG = "english"


def rebuild_search_vectors(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    Page.objects.update(
        search_vector=SearchVector("title", weight="A", config=SEARCH_CONFIG)
        + SearchVector("content", weight="B", config=SEARCH_CONFIG)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0020_zeroresultsearch"),
    ]

    operations = [
        migrations.RunPython(
            rebuild_search_vectors, migrations.RunPython.noop
        ),
    ]
