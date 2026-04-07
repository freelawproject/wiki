from django.db import migrations, models


def mark_existing_uploads(apps, schema_editor):
    """Mark all existing uploads so the daemon doesn't reprocess them."""
    FileUpload = apps.get_model("pages", "FileUpload")
    FileUpload.objects.all().update(optimization_gain=-1)


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
        migrations.RunPython(
            mark_existing_uploads,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
