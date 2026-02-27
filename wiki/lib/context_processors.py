from django.conf import settings


def inject_settings(request):
    """Inject specific settings into every template context."""
    return {
        "DEBUG": settings.DEBUG,
        "DEVELOPMENT": settings.DEVELOPMENT,
        "BASE_URL": settings.BASE_URL,
    }
