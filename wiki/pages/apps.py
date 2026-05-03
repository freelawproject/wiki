from django.apps import AppConfig


class PagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wiki.pages"

    def ready(self):
        from wiki.pages import signals  # noqa: F401
