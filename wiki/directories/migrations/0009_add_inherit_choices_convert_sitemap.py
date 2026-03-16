"""Add 'inherit' choice to all settings fields and convert in_sitemap to CharField.

Also migrates all existing data to use inheritance:
- in_sitemap: True -> "include", False -> "exclude"
- All non-root directories: set all four fields to "inherit"
"""

from django.db import migrations, models


def convert_sitemap_and_set_inherit(apps, schema_editor):
    Directory = apps.get_model("directories", "Directory")

    # Convert boolean in_sitemap values to string choices
    # (The field is now a CharField but old rows still have "True"/"False"
    # from the BooleanField → CharField conversion.)
    Directory.objects.filter(in_sitemap="True").update(in_sitemap="include")
    Directory.objects.filter(in_sitemap="False").update(in_sitemap="exclude")
    # Handle actual boolean values if the DB stores them differently
    Directory.objects.filter(in_sitemap="1").update(in_sitemap="include")
    Directory.objects.filter(in_sitemap="0").update(in_sitemap="exclude")

    # Set all non-root directories to inherit
    Directory.objects.exclude(path="").update(
        visibility="inherit",
        editability="inherit",
        in_sitemap="inherit",
        in_llms_txt="inherit",
    )


def reverse_migration(apps, schema_editor):
    # Not perfectly reversible, but set inherit back to defaults
    Directory = apps.get_model("directories", "Directory")
    Directory.objects.filter(visibility="inherit").update(visibility="public")
    Directory.objects.filter(editability="inherit").update(
        editability="restricted"
    )
    Directory.objects.filter(in_sitemap="inherit").update(in_sitemap="include")
    Directory.objects.filter(in_llms_txt="inherit").update(
        in_llms_txt="exclude"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("directories", "0008_update_llms_txt_choice_labels"),
    ]

    operations = [
        # 1. Convert in_sitemap from BooleanField to CharField
        migrations.AlterField(
            model_name="directory",
            name="in_sitemap",
            field=models.CharField(
                choices=[
                    ("include", "Yes"),
                    ("exclude", "No"),
                    ("inherit", "Inherit"),
                ],
                default="include",
                help_text="Include this directory in the sitemap.xml file.",
                max_length=10,
            ),
        ),
        # 2. Update visibility choices (add inherit)
        migrations.AlterField(
            model_name="directory",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("internal", "FLP Staff"),
                    ("private", "Private"),
                    ("inherit", "Inherit"),
                ],
                default="public",
                max_length=10,
            ),
        ),
        # 3. Update editability choices (add inherit)
        migrations.AlterField(
            model_name="directory",
            name="editability",
            field=models.CharField(
                choices=[
                    ("restricted", "Restricted"),
                    ("internal", "FLP Staff"),
                    ("inherit", "Inherit"),
                ],
                default="restricted",
                max_length=10,
            ),
        ),
        # 4. Update in_llms_txt choices (add inherit)
        migrations.AlterField(
            model_name="directory",
            name="in_llms_txt",
            field=models.CharField(
                choices=[
                    ("exclude", "No"),
                    ("include", "Yes"),
                    ("optional", "On request"),
                    ("inherit", "Inherit"),
                ],
                default="exclude",
                help_text="Whether to list this directory's pages in llms.txt.",
                max_length=10,
            ),
        ),
        # 5. Data migration: convert sitemap booleans and set non-root to inherit
        migrations.RunPython(
            convert_sitemap_and_set_inherit,
            reverse_migration,
        ),
    ]
