from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.checkout.models import PaymentSession
from apps.gateway.models import AliasVerification, RTPRequest
from apps.merchants.models import Merchant, MerchantApiKey
from apps.payments.models import Payment


class MerchantCheckoutCollectionApiTests(TestCase):
    url = "/api/v1/checkout/sessions/"
    verify_url = "/api/v1/checkout/alias-verifications/"

    def setUp(self):
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

    @patch("apps.gateway.services.client.create_rtp")
    @patch("apps.gateway.services.client.verify_alias")
    def test_one_request_verifies_alias_creates_session_payment_and_rtp(
        self, verify_alias, create_rtp
    ):
        verify_alias.return_value = {
            "found": True,
            "status": "ACTIVE",
            "customer": {"name": "Customer Name", "reference": "42"},
            "account": {"type": "MOBILE", "currency": "BIF"},
        }
        create_rtp.return_value = {
            "providerReference": "RTP-1001",
            "status": "PENDING",
        }
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["payer_alias"], "+25779000000")
        self.assertEqual(response.json()["payer_display_name"], "Customer Name")
        self.assertTrue(response.json()["payment_reference"].startswith("AMP-PAY-"))
        self.assertEqual(response.json()["payment_status"], "rtp_pending")
        self.assertEqual(PaymentSession.objects.count(), 1)
        self.assertEqual(AliasVerification.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(RTPRequest.objects.count(), 1)
        session = PaymentSession.objects.get()
        lifetime = session.expires_at - session.created_at
        self.assertAlmostEqual(lifetime.total_seconds(), 3 * 60 * 60, delta=2)
        alias_payload = verify_alias.call_args.args[0]
        self.assertEqual(alias_payload["aliasType"], "MOBILE")
        rtp_payload = create_rtp.call_args.args[0]
        self.assertEqual(rtp_payload["payerAlias"], "+25779000000")

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
        self.assertFalse(RTPRequest.objects.exists())
