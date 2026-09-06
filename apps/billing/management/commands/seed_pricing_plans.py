from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.models import PricingPlan


PLANS = (
    {
        "code": "starter",
        "name": "Starter",
        "description": "AmatoPay payment collection and settlement for new merchants.",
        "monthly_price": 250000,
        "included_transactions_per_month": 160,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
        ],
    },
    {
        "code": "standard",
        "name": "Standard",
        "description": "More processing capacity with delivery protection and request logs.",
        "monthly_price": 500000,
        "included_transactions_per_month": 320,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
            "Delivery protection",
            "Request logs",
        ],
    },
    {
        "code": "business",
        "name": "Business",
        "description": "Full-featured plan for established merchants.",
        "monthly_price": 850000,
        "included_transactions_per_month": 544,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
            "Delivery protection",
            "Request logs",
            "Refunds",
        ],
    },
    {
        "code": "business-plus",
        "name": "Business Plus",
        "description": "Business plan with priority support and KYB fast-track.",
        "monthly_price": 1050000,
        "included_transactions_per_month": 768,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
            "Delivery protection",
            "Request logs",
            "Refunds",
            "Priority support",
            "KYB fast-track",
        ],
    },
    {
        "code": "premium",
        "name": "Premium",
        "description": "High-volume plan with dedicated account manager and custom settlement.",
        "monthly_price": 1500000,
        "included_transactions_per_month": 960,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
            "Delivery protection",
            "Request logs",
            "Refunds",
            "Priority support",
            "KYB fast-track",
            "Dedicated account manager",
            "Custom settlement schedule",
        ],
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "description": "Contract plan with negotiated allowance, SLA, and compliance reporting.",
        "monthly_price": 2000000,
        "included_transactions_per_month": 1280,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
            "Delivery protection",
            "Request logs",
            "Refunds",
            "Priority support",
            "KYB fast-track",
            "Dedicated account manager",
            "Custom settlement schedule",
            "SLA guarantee",
            "Compliance reporting",
        ],
    },
    {
        "code": "unlimited",
        "name": "Unlimited",
        "description": "Unlimited monthly transactions with all Enterprise features included.",
        "monthly_price": 5000000,
        "included_transactions_per_month": None,
        "features": [
            "Unlimited transactions",
            "All Enterprise features",
            "White-glove onboarding",
            "Custom integration support",
            "SLA guarantee",
            "Compliance reporting",
        ],
    },
    {
        "code": "pay-as-you-go",
        "name": "Pay-as-you-go",
        "description": "5% fee on each transaction. No monthly commitment.",
        "monthly_price": 0,
        "included_transactions_per_month": 0,
        "transaction_fee_percentage": 0.05,
        "features": [
            "Hosted checkout",
            "Signed webhooks",
            "API access",
            "No monthly fee",
        ],
    },
)


class Command(BaseCommand):
    help = "Create or update the standard AmatoPay Gateway pricing plans."

    @transaction.atomic
    def handle(self, *args, **options):
        currency = "BIF"
        created_count = 0
        updated_count = 0
        for definition in PLANS:
            defaults = {**definition, "currency": currency, "active": True}
            code = defaults.pop("code")
            _, created = PricingPlan.objects.update_or_create(
                code=code,
                defaults=defaults,
            )
            created_count += int(created)
            updated_count += int(not created)
            self.stdout.write(f"  {'created' if created else 'updated'}: {defaults['name']}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPricing plans ready: {created_count} created, "
                f"{updated_count} updated ({currency})."
            )
        )
