from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.billing.models import PricingPlan


class SeedPricingPlansCommandTests(TestCase):
    def test_command_creates_gateway_plans_and_is_idempotent(self):
        output = StringIO()

        call_command("seed_pricing_plans", stdout=output)
        call_command("seed_pricing_plans", stdout=output)

        self.assertEqual(PricingPlan.objects.count(), 4)
        starter = PricingPlan.objects.get(code="starter")
        enterprise = PricingPlan.objects.get(code="enterprise")
        self.assertEqual(starter.included_transactions_per_month, 500)
        self.assertIsNone(enterprise.included_transactions_per_month)
        self.assertIn("0 created, 4 updated", output.getvalue())
