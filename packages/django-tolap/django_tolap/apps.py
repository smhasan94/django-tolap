from django.apps import AppConfig


class DjangoTolapConfig(AppConfig):
    name = "django_tolap"
    verbose_name = "TOLAP"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django_tolap import checks, lookups  # noqa: F401  registers system checks

        lookups.register()
