from django import template

from wiki.lib.users import display_name as _display_name

register = template.Library()


@register.filter
def display_name(user):
    """Return display name for a user, never showing a full email."""
    return _display_name(user)


@register.filter
def username_local(user):
    """Return the local part of a user's email username (before the @)."""
    username = getattr(user, "username", "")
    if "@" in username:
        return username.split("@")[0]
    return username
