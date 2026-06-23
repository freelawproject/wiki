from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("directories", "0011_directorypermission_domain_grant"),
    ]

    operations = [
        migrations.AddField(
            model_name="directory",
            name="seo_description",
            field=models.CharField(
                blank=True,
                help_text="Short summary for search engines and social "
                "cards. If blank, auto-generated from the directory "
                "description.",
                max_length=300,
            ),
        ),
    ]
