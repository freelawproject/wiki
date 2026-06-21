from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("directories", "0010_fix_lowercase_boolean_sitemap"),
    ]

    operations = [
        migrations.AddField(
            model_name="directorypermission",
            name="grant_domain",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=255,
                help_text=(
                    "Normalized email domain (e.g. 'acme.com') granted "
                    "access. Stored as a string, not a FK, so the grant "
                    "survives the domain leaving the sign-in allowlist and "
                    "re-binds if it is re-added."
                ),
            ),
        ),
        migrations.AddField(
            model_name="directorypermission",
            name="dormant_since",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "Set when a domain grant's domain leaves the allowlist; "
                    "cleared when it returns. Grants dormant past the "
                    "retention window are removed by the cleanup job."
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="directorypermission",
            constraint=models.UniqueConstraint(
                condition=models.Q(grant_domain__isnull=False),
                fields=("directory", "grant_domain", "permission_type"),
                name="unique_dir_domain_perm",
            ),
        ),
        # Relabel the "internal" choice display "FLP Staff" -> "Staff".
        migrations.AlterField(
            model_name="directory",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("internal", "Staff"),
                    ("private", "Private"),
                    ("inherit", "Inherit"),
                ],
                default="public",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="directory",
            name="editability",
            field=models.CharField(
                choices=[
                    ("restricted", "Restricted"),
                    ("internal", "Staff"),
                    ("inherit", "Inherit"),
                ],
                default="restricted",
                max_length=10,
            ),
        ),
    ]
