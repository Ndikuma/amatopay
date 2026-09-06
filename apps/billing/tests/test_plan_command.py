from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.billing.models import PricingPlan
from apps.billing.management.commands.seed_pricing_plans import PLANS


class SeedPricingPlansCommandTests(TestCase):
    def test_command_creates_gateway_plans_and_is_idempotent(self):
        output = StringIO()

        call_command("seed_pricing_plans", stdout=output)
        call_command("seed_pricing_plans", stdout=output)

        self.assertEqual(PricingPlan.objects.count(), len(PLANS))
        starter = PricingPlan.objects.get(code="starter")
        unlimited = PricingPlan.objects.get(code="unlimited")
        self.assertEqual(starter.included_transactions_per_month, 160)
        self.assertIsNone(unlimited.included_transactions_per_month)
        self.assertIn(f"0 created, {len(PLANS)} updated", output.getvalue())
