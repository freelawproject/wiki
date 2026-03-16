"""Fix leftover lowercase boolean strings from PostgreSQL bool→varchar cast.

PostgreSQL converts boolean true/false to lowercase 'true'/'false' when
altering to varchar, but migration 0014 only checked for 'True'/'False'
(capital T/F). This catches any remaining lowercase values.
"""

from django.db import migrations


def fix_lowercase_booleans(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    all_pages = Page._default_manager
    all_pages.filter(in_sitemap="true").update(in_sitemap="include")
    all_pages.filter(in_sitemap="false").update(in_sitemap="exclude")


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0014_add_inherit_choices_convert_sitemap"),
    ]

    operations = [
        migrations.RunPython(fix_lowercase_booleans, migrations.RunPython.noop),
    ]
