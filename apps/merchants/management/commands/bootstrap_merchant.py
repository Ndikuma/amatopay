from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.merchants.models import Merchant, MerchantApiKey


class Command(BaseCommand):
    def add_arguments(self, p):
        p.add_argument("--name", required=True)
        p.add_argument("--email", required=True)
        p.add_argument("--code", required=True)

    @transaction.atomic
    def handle(self, *a, **o):
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username=o["email"], defaults={"email": o["email"]}
        )
        m, _ = Merchant.objects.get_or_create(
            merchant_code=o["code"],
            defaults={
                "legal_name": o["name"],
                "display_name": o["name"],
                "email": o["email"],
                "status": "active",
            },
        )
        if m.owner_id != user.id:
            m.owner = user
            m.save(update_fields=["owner", "updated_at"])
        key, raw = MerchantApiKey.issue(m, "Integration key")
        self.stdout.write(
            self.style.SUCCESS(
                f"Merchant: {m.merchant_code}\nTest API key (shown once): {raw}"
            )
        )
