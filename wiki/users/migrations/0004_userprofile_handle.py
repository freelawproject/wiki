import re

from django.db import migrations, models

HANDLE_MAX = 64
_STRIP = re.compile(r"[^a-z0-9._-]+")


def _compose(base, tail):
    if not tail:
        return base[:HANDLE_MAX]
    keep = HANDLE_MAX - len(tail) - 1
    return f"{base[:keep]}-{tail}"


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

    profiles = UserProfile.objects.select_related("user").order_by(
        "user__date_joined", "user__id"
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
        p.save(update_fields=["handle"])


def clear_handles(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.update(handle=None)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_alloweddomain_suffix"),
    ]

    operations = [
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
        migrations.RunPython(backfill_handles, clear_handles),
    ]
