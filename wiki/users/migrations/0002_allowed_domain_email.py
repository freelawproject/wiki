from django.db import migrations, models


def seed_free_law(apps, schema_editor):
    """Preserve existing behavior by allowing the free.law domain."""
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    AllowedDomain.objects.get_or_create(
        domain="free.law",
        defaults={"note": "Free Law Project staff"},
    )


def unseed_free_law(apps, schema_editor):
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    AllowedDomain.objects.filter(domain="free.law").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AllowedDomain",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("domain", models.CharField(max_length=255, unique=True)),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        help_text="Optional reminder of why this domain is allowed.",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["domain"],
            },
        ),
        migrations.CreateModel(
            name="AllowedEmail",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("email", models.EmailField(max_length=254, unique=True)),
                (
                    "note",
                    models.CharField(
                        blank=True,
                        help_text="Optional reminder of why this address is allowed.",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["email"],
            },
        ),
        migrations.RunPython(seed_free_law, unseed_free_law),
    ]
