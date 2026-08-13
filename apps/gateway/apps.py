from django.apps import AppConfig


class GatewayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.gateway"
    # Preserve migration history and existing cecf_* database tables.
    label = "cecf"
    verbose_name = "Payment gateway"

    def ready(self):
        from . import checks  # noqa: F401
        from . import handlers  # noqa: F401
