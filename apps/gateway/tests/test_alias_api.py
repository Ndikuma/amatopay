from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.models import PricingPlan
from apps.checkout.models import PaymentSession
from apps.gateway.models import AliasVerification, GatewayRequest
from apps.merchants.models import Merchant, MerchantApiKey
from apps.payments.models import Payment


class MerchantCheckoutCollectionApiTests(TestCase):
    url = "/api/v1/checkout/sessions/"
    verify_url = "/api/v1/checkout/alias-verifications/"

    def setUp(self):
        PricingPlan.objects.create(
            code="pay-as-you-go",
            name="Pay-as-you-go",
            currency="BIF",
            transaction_fee_percentage=Decimal("5"),
        )
        merchant = Merchant.objects.create(
            merchant_code="AMP-ALIAS-TEST",
            legal_name="Alias Test Merchant",
            display_name="Alias Test Merchant",
            status=Merchant.Status.ACTIVE,
        )
        _, self.raw_key = MerchantApiKey.issue(merchant, "Checkout API")
        self.client = APIClient()
        self.payload = {
            "order_number": "ORDER-1001",
            "description": "Protected order",
            "amount": "100000.00",
            "currency": "BIF",
            "payer_alias": "+25779000000",
        }

    def test_api_key_is_required(self):
        response = self.client.get(self.verify_url, {"payer_alias": "+25779000000"})
        self.assertIn(response.status_code, {401, 403})

    @patch("apps.gateway.services.client.create_collection")
    @patch("apps.gateway.services.client.verify_alias")
    def test_checkout_creates_session_and_payment_without_waiting_for_the_rail(
        self, verify_alias, create_collection
    ):
        verify_alias.return_value = {
            "found": True,
            "status": "ACTIVE",
            "customer": {"name": "Customer Name", "reference": "42"},
            "account": {"type": "MOBILE", "currency": "BIF"},
        }
        create_collection.return_value = {
            "providerReference": "RTP-1001",
            "status": "PENDING",
        }
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.post(self.url, self.payload, format="json")

        # The merchant request returns immediately; the gateway is not called.
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["payer_alias"], "+25779000000")
        self.assertEqual(response.json()["payer_display_name"], "Customer Name")
        self.assertTrue(response.json()["payment_reference"].startswith("AMP-PAY-"))
        self.assertEqual(response.json()["payment_status"], "alias_verified")
        self.assertEqual(PaymentSession.objects.count(), 1)
        self.assertEqual(AliasVerification.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(GatewayRequest.objects.count(), 0)
        create_collection.assert_not_called()
        session = PaymentSession.objects.get()
        lifetime = session.expires_at - session.created_at
        self.assertAlmostEqual(lifetime.total_seconds(), 3 * 60 * 60, delta=2)
        alias_payload = verify_alias.call_args.args[0]
        self.assertEqual(alias_payload["aliasType"], "MOBILE")

        # The background worker submits the collection.
        call_command("process_pending_payments")

        self.assertEqual(GatewayRequest.objects.count(), 1)
        Payment.objects.get().refresh_from_db()
        self.assertEqual(Payment.objects.get().status, "collection_pending")
        collection_payload = create_collection.call_args.args[0]
        self.assertEqual(collection_payload["payerAlias"], "+25779000000")

    @patch("apps.gateway.services.client.verify_alias")
    def test_alias_name_can_be_looked_up_with_get(self, verify_alias):
        verify_alias.return_value = {
            "found": True,
            "status": "ACTIVE",
            "customer": {"name": "Customer Name"},
            "account": {"type": "MOBILE", "currency": "BIF"},
        }
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

        response = self.client.get(
            self.verify_url, {"payer_alias": "+25779000000"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["payer_alias"], "+25779000000")
        self.assertEqual(response.json()["customer_full_name"], "Customer Name")
        self.assertNotIn("verification_id", response.json())
        self.assertNotIn("expires_at", response.json())

    @patch("apps.gateway.services.client.verify_alias")
    def test_invalid_alias_creates_no_financial_records(self, verify_alias):
        verify_alias.return_value = {"found": False, "status": "NOT_FOUND"}
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

        response = self.client.post(
            self.url, self.payload, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("payer_alias", response.json())
        self.assertFalse(PaymentSession.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(GatewayRequest.objects.exists())
