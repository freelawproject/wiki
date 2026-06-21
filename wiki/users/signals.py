"""Signal handlers for the users app."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from wiki.lib.users import assign_handle
from wiki.users.models import UserProfile


@receiver(post_save, sender=UserProfile)
def assign_handle_on_create(sender, instance, created, **kwargs):
    """Give every new profile a unique handle.

    Centralizes assignment so it happens however a profile is created
    (login, admin, fixtures). ``assign_handle`` is idempotent and saves
    only the ``handle`` field, so the re-entrant post_save it triggers is a
    no-op.
    """
    if created and not instance.handle:
        assign_handle(instance)
