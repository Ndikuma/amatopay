from django.core.checks import Warning, register
from django.db import OperationalError, ProgrammingError

from .models import GatewayConfig


@register()
def gateway_configuration_check(app_configs, **kwargs):
    try:
        configured = GatewayConfig.active()
    except (OperationalError, ProgrammingError):
        return []
    if configured and all(
        [
            configured.base_url,
            configured.username,
            configured.password,
            configured.creditor_alias,
        ]
    ):
        return []
    detail = "no active configuration"
    if configured:
        missing = [
            name
            for name in ("base_url", "username", "password", "creditor_alias")
            if not getattr(configured, name)
        ]
        detail = f"missing database fields: {', '.join(missing)}"
    return [
        Warning(
            f"MobileCash gateway configuration is incomplete ({detail}).",
            hint="Create, verify, and activate a Gateway configuration in Django Admin before accepting production payments.",
            id="gateway.W001",
        )
    ]


@register()
def fiduciary_account_check(app_configs, **kwargs):
    from apps.fiduciary.models import FiduciaryAccount

    try:
        configured = GatewayConfig.active()
        account = FiduciaryAccount.objects.first()
    except (OperationalError, ProgrammingError):
        return []
    if not configured:
        return []
    if (
        account
        and account.active
        and account.verified_at
        and account.creditor_alias == configured.creditor_alias
        and account.account_number
    ):
        return []
    return [
        Warning(
            "The AmatoPay fiduciary account is missing, unverified, or does not match the active gateway creditor alias.",
            hint="Run: python manage.py sync_fiduciary_account",
            id="gateway.W002",
        )
    ]
