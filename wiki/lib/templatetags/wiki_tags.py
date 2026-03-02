from django import template

from wiki.lib.users import display_name as _display_name

register = template.Library()


@register.filter
def display_name(user):
    """Return display name for a user, never showing a full email."""
    return _display_name(user)
