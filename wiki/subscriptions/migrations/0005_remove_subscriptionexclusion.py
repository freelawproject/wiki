"""Remove the SubscriptionExclusion model.

All exclusion data has been migrated into status='unsubscribed' records
on PageSubscription / DirectorySubscription by migration 0004.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0004_convert_exclusions"),
    ]

    operations = [
        migrations.DeleteModel(
            name="SubscriptionExclusion",
        ),
    ]
