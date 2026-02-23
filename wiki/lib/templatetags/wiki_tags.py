from django import template

register = template.Library()


@register.filter
def display_name(user):
    """Return display name for a user, never showing a full email.

    Priority: profile.display_name > first part of email > "Unknown"
    """
    if not user:
        return "Unknown"
    if hasattr(user, "profile"):
        try:
            name = user.profile.display_name
            if name:
                return name
        except Exception:
            pass
    email = getattr(user, "email", "")
    if email and "@" in email:
        return email.split("@")[0]
    return getattr(user, "username", "Unknown").split("@")[0]
