from django.db import migrations, models


def make_free_law_staff(apps, schema_editor):
    """The seeded free.law domain is staff; everything else stays third-party."""
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    AllowedDomain.objects.filter(domain="free.law").update(tier="staff")


def reset_tier(apps, schema_editor):
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    AllowedDomain.objects.filter(domain="free.law").update(tier="third_party")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_userprofile_handle"),
    ]

    operations = [
        migrations.AddField(
            model_name="alloweddomain",
            name="tier",
            field=models.CharField(
                choices=[("staff", "Staff"), ("third_party", "Third party")],
                default="third_party",
                help_text=(
                    "Staff see internal content without an explicit grant; "
                    "third parties only see public content plus what they're "
                    "granted."
                ),
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="allowedemail",
            name="tier",
            field=models.CharField(
                choices=[("staff", "Staff"), ("third_party", "Third party")],
                default="third_party",
                help_text=(
                    "Staff see internal content without an explicit grant; "
                    "third parties only see public content plus what they're "
                    "granted. Overrides the tier of the address's domain, if "
                    "any."
                ),
                max_length=12,
            ),
        ),
        migrations.RunPython(make_free_law_staff, reset_tier),
    ]
