"""Convert SubscriptionExclusion records into status='unsubscribed' records.

- Page exclusion → PageSubscription(status='unsubscribed')
- Directory exclusion → DirectorySubscription(status='unsubscribed')

Skips if a subscription record already exists for the same user+target
(existing SUBSCRIBED record takes precedence as the more authoritative
state — the exclusion was only relevant for blocking directory inheritance,
which the explicit subscribe already overrides).
"""

from django.db import migrations


def convert_exclusions(apps, schema_editor):
    SubscriptionExclusion = apps.get_model(
        "subscriptions", "SubscriptionExclusion"
    )
    PageSubscription = apps.get_model("subscriptions", "PageSubscription")
    DirectorySubscription = apps.get_model(
        "subscriptions", "DirectorySubscription"
    )

    for excl in SubscriptionExclusion.objects.filter(page__isnull=False):
        if not PageSubscription.objects.filter(
            user_id=excl.user_id, page_id=excl.page_id
        ).exists():
            PageSubscription.objects.create(
                user_id=excl.user_id,
                page_id=excl.page_id,
                status="unsubscribed",
            )

    for excl in SubscriptionExclusion.objects.filter(directory__isnull=False):
        if not DirectorySubscription.objects.filter(
            user_id=excl.user_id, directory_id=excl.directory_id
        ).exists():
            DirectorySubscription.objects.create(
                user_id=excl.user_id,
                directory_id=excl.directory_id,
                status="unsubscribed",
            )


def reverse_conversion(apps, schema_editor):
    """Remove the records we created (best-effort reverse)."""
    PageSubscription = apps.get_model("subscriptions", "PageSubscription")
    DirectorySubscription = apps.get_model(
        "subscriptions", "DirectorySubscription"
    )

    PageSubscription.objects.filter(status="unsubscribed").delete()
    DirectorySubscription.objects.filter(status="unsubscribed").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0003_add_status_field"),
    ]

    operations = [
        migrations.RunPython(convert_exclusions, reverse_conversion),
    ]
