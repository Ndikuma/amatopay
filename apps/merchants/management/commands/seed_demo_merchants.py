from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.merchants.models import (
    BeneficialOwner,
    Merchant,
    MerchantApiKey,
    MerchantDocument,
    MerchantKYB,
    MerchantSettlementAccount,
)

MERCHANTS = [
    {
        "code": "AMP-MER-000001",
        "name": "Akarusho Market",
        "email": "owner@akarusho.bi",
        "phone": "+257 79 100 001",
        "city": "Bujumbura",
        "address": "Avenue de la Mission 12",
        "registration": "RC-BJM-2026-1001",
        "tax": "NIF-400100001",
        "alias": "+25779100001",
        "owner": "Aline Ndayizeye",
    },
    {
        "code": "AMP-MER-000002",
        "name": "Buja Fresh",
        "email": "owner@bujafresh.bi",
        "phone": "+257 79 100 002",
        "city": "Bujumbura",
        "address": "Boulevard de l'Uprona 48",
        "registration": "RC-BJM-2026-1002",
        "tax": "NIF-400100002",
        "alias": "+25779100002",
        "owner": "Chris Irakoze",
    },
    {
        "code": "AMP-MER-000003",
        "name": "Ikaze Shop",
        "email": "owner@ikazeshop.bi",
        "phone": "+257 79 100 003",
        "city": "Gitega",
        "address": "Quartier Nyamugari 7",
        "registration": "RC-GIT-2026-1003",
        "tax": "NIF-400100003",
        "alias": "+25779100003",
        "owner": "Diane Niyonkuru",
    },
    {
        "code": "AMP-MER-000004",
        "name": "Kaze Logistics",
        "email": "owner@kazelogistics.bi",
        "phone": "+257 79 100 004",
        "city": "Bujumbura",
        "address": "Chaussée de l'Agriculture 21",
        "registration": "RC-BJM-2026-1004",
        "tax": "NIF-400100004",
        "alias": "+25779100004",
        "owner": "Eric Nkurunziza",
    },
    {
        "code": "AMP-MER-000005",
        "name": "Tanganyika Digital",
        "email": "owner@tanganyika.bi",
        "phone": "+257 79 100 005",
        "city": "Rumonge",
        "address": "Avenue du Port 5",
        "registration": "RC-RMG-2026-1005",
        "tax": "NIF-400100005",
        "alias": "+25779100005",
        "owner": "Fabiola Nahimana",
    },
]


class Command(BaseCommand):
    help = "Create or refresh five complete demo merchant workspaces."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="password123")

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]
        User = get_user_model()
        credentials = []

        for index, data in enumerate(MERCHANTS, start=1):
            first_name, last_name = data["owner"].split(" ", 1)
            user, _ = User.objects.update_or_create(
                username=data["email"],
                defaults={
                    "email": data["email"],
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_active": True,
                },
            )
            user.set_password(password)
            user.save(update_fields=["password"])

            merchant, _ = Merchant.objects.update_or_create(
                merchant_code=data["code"],
                defaults={
                    "legal_name": f'{data["name"]} SURL',
                    "display_name": data["name"],
                    "legal_form": "SURL",
                    "registration_number": data["registration"],
                    "tax_id": data["tax"],
                    "email": data["email"],
                    "phone": data["phone"],
                    "country": "BI",
                    "city": data["city"],
                    "address": data["address"],
                    "website": f'https://{data["email"].split("@", 1)[1]}',
                    "mcc": "5399",
                    "status": Merchant.Status.ACTIVE,
                    "risk_rating": "low",
                    "default_currency": "BIF",
                    "statement_descriptor": data["name"][:22].upper(),
                    "metadata": {"demo": True, "seed_version": 1},
                },
            )
            if merchant.owner_id != user.id:
                merchant.owner = user
                merchant.save(update_fields=["owner", "updated_at"])
            MerchantKYB.objects.update_or_create(
                merchant=merchant,
                defaults={
                    "decision": MerchantKYB.Decision.APPROVED,
                    "verified": True,
                    "verified_at": timezone.now(),
                    "reviewed_by": "AmatoPay Demo Operations",
                    "source_of_funds": "Retail and e-commerce sales",
                    "expected_monthly_volume": Decimal("25000000.00") * index,
                    "expected_monthly_transactions": 250 * index,
                    "risk_rating": "low",
                },
            )
            for document_type, number in (
                (MerchantDocument.Type.REGISTRATION, data["registration"]),
                (MerchantDocument.Type.TAX, data["tax"]),
                (MerchantDocument.Type.ID, f"ID-DEMO-{index:04d}"),
            ):
                MerchantDocument.objects.update_or_create(
                    merchant=merchant,
                    document_type=document_type,
                    defaults={"document_number": number, "verified": True},
                )
            BeneficialOwner.objects.update_or_create(
                merchant=merchant,
                full_name=data["owner"],
                defaults={
                    "nationality": "BI",
                    "id_number": f"ID-DEMO-{index:04d}",
                    "ownership_percent": Decimal("100.00"),
                    "pep": False,
                    "sanctions_match": False,
                },
            )
            MerchantSettlementAccount.objects.update_or_create(
                merchant=merchant,
                alias_type="MOBILE",
                alias_value=data["alias"],
                defaults={
                    "account_name": data["name"],
                    "account_type": "MOBILE",
                    "currency": "BIF",
                    "provider_customer_reference": f"DEMO-CUST-{index:04d}",
                    "verification_status": MerchantSettlementAccount.Verification.VERIFIED,
                    "verified_at": timezone.now(),
                    "is_primary": True,
                    "is_active": True,
                    "raw_verification": {"demo": True, "status": "verified"},
                },
            )
            if not merchant.api_keys.filter(name="Demo integration key").exists():
                MerchantApiKey.issue(merchant, "Demo integration key")
            credentials.append((data["name"], data["email"], data["code"]))

        self.stdout.write(
            self.style.SUCCESS("Created/refreshed 5 complete demo merchants:")
        )
        for name, email, code in credentials:
            self.stdout.write(f"  {name:<22} {email:<28} {code}")
        self.stdout.write(self.style.WARNING(f"Shared demo password: {password}"))
