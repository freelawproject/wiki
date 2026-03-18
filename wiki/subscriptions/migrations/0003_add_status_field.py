"""Add status field to PageSubscription and DirectorySubscription.

Existing records get status='subscribed' (the default), which preserves
their current meaning: a record existed only for subscribed users.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0002_directorysubscription_subscriptionexclusion"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagesubscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("subscribed", "Subscribed"),
                    ("unsubscribed", "Unsubscribed"),
                ],
                default="subscribed",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="directorysubscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("subscribed", "Subscribed"),
                    ("unsubscribed", "Unsubscribed"),
                ],
                default="subscribed",
                max_length=20,
            ),
        ),
    ]
