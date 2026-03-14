from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0008_soft_delete_pages"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="is_pinned",
            field=models.BooleanField(
                default=False,
                help_text="Pinned pages appear at the top of directory listings.",
            ),
        ),
    ]
