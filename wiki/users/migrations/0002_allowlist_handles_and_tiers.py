import re

from django.db import migrations, models

HANDLE_MAX = 64
_STRIP = re.compile(r"[^a-z0-9._-]+")


def _compose(base, tail):
    if not tail:
        return base[:HANDLE_MAX]
    keep = HANDLE_MAX - len(tail) - 1
    return f"{base[:keep]}-{tail}"


def seed_free_law(apps, schema_editor):
    """Preserve existing access: free.law is an allowed, staff-tier domain.

    Seeded with the ``flp`` handle suffix so a colliding free.law handle
    disambiguates to ``<name>-flp``.
    """
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    AllowedDomain.objects.get_or_create(
        domain="free.law",
        defaults={
            "suffix": "flp",
            "tier": "staff",
            "note": "Free Law Project staff",
        },
    )


def unseed_free_law(apps, schema_editor):
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    AllowedDomain.objects.filter(domain="free.law").delete()


def backfill_handles(apps, schema_editor):
    """Assign a unique handle to every existing profile.

    Deterministic by (date_joined, id) so the first claimant of a base keeps
    it. Mirrors wiki.lib.users.assign_handle; kept self-contained per the
    migration contract. Existing single-domain users never collide (email is
    unique within a domain), so they all get bare handles.
    """
    UserProfile = apps.get_model("users", "UserProfile")
    AllowedDomain = apps.get_model("users", "AllowedDomain")
    suffix_by_domain = {
        d.domain: d.suffix for d in AllowedDomain.objects.all()
    }
    taken = set()

    # Stream rows (bounded memory) and persist in batches rather than one
    # UPDATE per row, so this scales to a large existing user base. The
    # taken-set + (date_joined, id) ordering keep handle assignment
    # deterministic and collision-free regardless of batching.
    BATCH = 1000
    pending = []

    def flush():
        if pending:
            UserProfile.objects.bulk_update(pending, ["handle"])
            pending.clear()

    profiles = (
        UserProfile.objects.select_related("user")
        .order_by("user__date_joined", "user__id")
        .iterator(chunk_size=BATCH)
    )
    for p in profiles:
        if p.handle:
            taken.add(p.handle)
            continue
        email = (p.user.email or "").lower()
        local = email.split("@", 1)[0]
        base = _STRIP.sub("", local).lstrip("._-")
        if not base or not base[0].isalpha():
            base = "u" + base
        base = base[:50]

        candidate = _compose(base, "")
        if candidate in taken:
            domain = email.split("@", 1)[1] if "@" in email else ""
            suffix = suffix_by_domain.get(domain)
            if suffix:
                candidate = _compose(base, suffix)
                n = 2
                while candidate in taken:
                    candidate = _compose(base, f"{suffix}-{n}")
                    n += 1
            else:
                n = 2
                candidate = _compose(base, str(n))
                while candidate in taken:
                    n += 1
                    candidate = _compose(base, str(n))

        p.handle = candidate
        taken.add(candidate)
        pending.append(p)
        if len(pending) >= BATCH:
            flush()

    flush()


def clear_handles(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.update(handle=None)


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
                    "tier",
                    models.CharField(
                        choices=[("staff", "Staff"), ("guest", "Guest")],
                        default="guest",
                        help_text=(
                            "Staff see internal content without an explicit "
                            "grant; guests only see public content plus what "
                            "they're granted."
                        ),
                        max_length=12,
                    ),
                ),
                (
                    "suffix",
                    models.CharField(
                        help_text=(
                            "Short slug appended to a handle when it collides "
                            "with an existing one, e.g. 'flp' turns a "
                            "colliding mike@free.law into 'mike-flp'. Used "
                            "only on actual collisions."
                        ),
                        max_length=32,
                        unique=True,
                    ),
                ),
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
                    "tier",
                    models.CharField(
                        choices=[("staff", "Staff"), ("guest", "Guest")],
                        default="guest",
                        help_text=(
                            "Staff see internal content without an explicit "
                            "grant; guests only see public content plus what "
                            "they're granted. Overrides the tier of the "
                            "address's domain, if any."
                        ),
                        max_length=12,
                    ),
                ),
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
        migrations.AddField(
            model_name="userprofile",
            name="handle",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Unique public @-handle, assigned at first sign-in. "
                    "Derived from the email local part, disambiguated on "
                    "collision."
                ),
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        # Seed before backfilling handles: the handle collision logic reads
        # AllowedDomain suffixes.
        migrations.RunPython(seed_free_law, unseed_free_law),
        migrations.RunPython(backfill_handles, clear_handles),
    ]
