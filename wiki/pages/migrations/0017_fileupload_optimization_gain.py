from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0016_add_data_source_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="fileupload",
            name="optimization_gain",
            field=models.IntegerField(
                blank=True,
                help_text=(
                    "Bytes saved by optimization. "
                    "Null=pending, positive=saved, negative=grew, 0=error."
                ),
                null=True,
            ),
        ),
    ]
