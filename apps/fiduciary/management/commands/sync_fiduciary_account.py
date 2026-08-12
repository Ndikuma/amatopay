import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.fiduciary.models import FiduciaryAccount
from apps.gateway import client
from apps.gateway.models import GatewayConfig


class Command(BaseCommand):
    help = (
        "Verify the active gateway creditor alias and synchronize the single "
        "AmatoPay fiduciary account."
    )

    def handle(self, *args, **options):
        config = GatewayConfig.objects.filter(is_active=True).first()
        if not config:
            raise CommandError("No active gateway configuration exists.")
        if not config.creditor_alias.strip():
            raise CommandError("The active gateway has no creditor alias.")

        request_id = f"AMP-FID-{uuid.uuid4().hex[:16].upper()}"
        try:
            result = client.verify_alias(
                {
                    "requestId": request_id,
                    "alias": config.creditor_alias.strip(),
                    "aliasType": "MOBILE",
                }
            )
        except Exception as exc:
            raise CommandError(f"Gateway alias verification failed: {exc}") from exc

        if not result.get("found") or str(result.get("status", "")).upper() != "ACTIVE":
            raise CommandError("The gateway creditor alias is not active and payable.")

        account_data = result.get("account") or {}
        account_number = str(account_data.get("number") or "").strip()
        if not account_number:
            raise CommandError(
                "Gateway verification succeeded but did not return an account number."
            )

        customer_data = result.get("customer") or {}
        account_name = str(
            account_data.get("name")
            or customer_data.get("name")
            or "AmatoPay fiduciary account"
        ).strip()
        currency = str(account_data.get("currency") or "BIF").upper()[:3]
        account, created = self._synchronize(
            creditor_alias=config.creditor_alias.strip(),
            account_number=account_number,
            account_name=account_name,
            currency=currency,
            verification=result,
        )

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} fiduciary account {account.account_number} "
                f"for creditor alias {account.creditor_alias}."
            )
        )

    @staticmethod
    @transaction.atomic
    def _synchronize(
        *, creditor_alias, account_number, account_name, currency, verification
    ):
        account = FiduciaryAccount.objects.select_for_update().first()
        created = account is None
        if created:
            account = FiduciaryAccount()
        account.alias_type = "MOBILE"
        account.creditor_alias = creditor_alias
        account.account_number = account_number
        account.account_name = account_name[:180]
        account.currency = currency
        account.active = True
        account.verified_at = timezone.now()
        account.raw_verification = verification
        account.save()
        return account, created
