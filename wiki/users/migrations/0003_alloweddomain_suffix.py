import re

from django.db import migrations, models


def set_suffixes(apps, schema_editor):
    """Give every existing domain a unique handle suffix.

    The seeded ``free.law`` becomes ``flp``; any other pre-existing domain
    gets a slug of its first label, de-duplicated with a number.
    """
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    used = set()
    for d in AllowedDomain.objects.all().order_by("id"):
        if d.domain == "free.law":
            base = "flp"
        else:
            base = re.sub(r"[^a-z0-9]", "", d.domain.split(".")[0].lower())
            base = base or "org"
        suffix = base
        n = 2
        while suffix in used:
            suffix = f"{base}{n}"
            n += 1
        d.suffix = suffix
        used.add(suffix)
        d.save(update_fields=["suffix"])


def clear_suffixes(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_allowed_domain_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="alloweddomain",
            name="suffix",
            field=models.CharField(max_length=32, null=True),
        ),
        migrations.RunPython(set_suffixes, clear_suffixes),
        migrations.AlterField(
            model_name="alloweddomain",
            name="suffix",
            field=models.CharField(
                help_text=(
                    "Short slug appended to a handle when it collides with "
                    "an existing one, e.g. 'flp' turns a colliding "
                    "mike@free.law into 'mike-flp'. Used only on actual "
                    "collisions."
                ),
                max_length=32,
                unique=True,
            ),
        ),
    ]
