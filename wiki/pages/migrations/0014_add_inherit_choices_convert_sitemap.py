"""Add 'inherit' choice to all settings fields and convert in_sitemap to CharField.

Also migrates all existing data to use inheritance:
- in_sitemap: True -> "include", False -> "exclude"
- All pages: set all four fields to "inherit"
- Delete all PagePermission records
"""

from django.db import migrations, models


def convert_sitemap_and_set_inherit(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    PagePermission = apps.get_model("pages", "PagePermission")
    # Use _default_manager to bypass ActivePageManager filter
    all_pages = Page._default_manager

    # Convert boolean in_sitemap values to string choices
    all_pages.filter(in_sitemap="True").update(in_sitemap="include")
    all_pages.filter(in_sitemap="False").update(in_sitemap="exclude")
    all_pages.filter(in_sitemap="1").update(in_sitemap="include")
    all_pages.filter(in_sitemap="0").update(in_sitemap="exclude")

    # Set all pages to inherit
    all_pages.update(
        visibility="inherit",
        editability="inherit",
        in_sitemap="inherit",
        in_llms_txt="inherit",
    )

    # Delete all page-level permissions
    PagePermission.objects.all().delete()


def reverse_migration(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    all_pages = Page._default_manager
    all_pages.filter(visibility="inherit").update(visibility="public")
    all_pages.filter(editability="inherit").update(editability="restricted")
    all_pages.filter(in_sitemap="inherit").update(in_sitemap="include")
    all_pages.filter(in_llms_txt="inherit").update(in_llms_txt="exclude")


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0013_update_llms_txt_choice_labels"),
    ]

    operations = [
        # 1. Convert in_sitemap from BooleanField to CharField
        migrations.AlterField(
            model_name="page",
            name="in_sitemap",
            field=models.CharField(
                choices=[
                    ("include", "Yes"),
                    ("exclude", "No"),
                    ("inherit", "Inherit"),
                ],
                default="include",
                help_text="Include this page in the sitemap.xml file.",
                max_length=10,
            ),
        ),
        # 2. Update visibility choices (add inherit)
        migrations.AlterField(
            model_name="page",
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
            model_name="page",
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
            model_name="page",
            name="in_llms_txt",
            field=models.CharField(
                choices=[
                    ("exclude", "No"),
                    ("include", "Yes"),
                    ("optional", "On request"),
                    ("inherit", "Inherit"),
                ],
                default="exclude",
                help_text="Whether to list this page in llms.txt.",
                max_length=10,
            ),
        ),
        # 5. Data migration: convert sitemap booleans, set inherit, delete perms
        migrations.RunPython(
            convert_sitemap_and_set_inherit,
            reverse_migration,
        ),
    ]
