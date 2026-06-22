from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_allowlist_handles_and_tiers"),
    ]

    operations = [
        migrations.AddField(
            model_name="alloweddomain",
            name="favicon_data",
            field=models.BinaryField(
                blank=True,
                null=True,
                help_text=(
                    "The domain's favicon, fetched server-side and normalized "
                    "to a small PNG. Null when not yet fetched or unavailable."
                ),
            ),
        ),
        migrations.AddField(
            model_name="alloweddomain",
            name="favicon_checked_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "When the favicon was last fetched (success or failure); "
                    "drives periodic refresh and retry."
                ),
            ),
        ),
    ]
