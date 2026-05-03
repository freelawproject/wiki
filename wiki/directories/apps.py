from django.apps import AppConfig


class DirectoriesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wiki.directories"

    def ready(self):
        from wiki.directories import signals  # noqa: F401
