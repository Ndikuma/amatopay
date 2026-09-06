from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.merchants.models import (
    Merchant,
    MerchantApiKey,
    MerchantDocument,
    MerchantKYB,
    MerchantSettlementAccount,
)


class MerchantPingTests(TestCase):
    url = "/api/v1/ping/"

    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-PING-1",
            legal_name="Ping Test SA",
            display_name="Ping Test",
            registration_number="RC-1",
            tax_id="NIF-1",
            email="ops@ping.bi",
            phone="+25779000000",
            address="Rohero, Bujumbura",
            status=Merchant.Status.PENDING_KYB,
        )
        _, self.raw_key = MerchantApiKey.issue(self.merchant, "Ping API")
        self.client = APIClient()

    def test_ping_requires_api_key(self):
        self.assertIn(self.client.get(self.url).status_code, {401, 403})

    def test_ping_accepts_the_api_key_both_ways(self):
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        self.assertEqual(self.client.get(self.url).status_code, 200)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key}")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_ping_reports_pending_verification(self):
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("review", body["message"].lower())
        self.assertFalse(body["can_operate"])
        self.assertEqual(body["merchant"]["code"], "AMP-PING-1")
        self.assertLess(body["verification"]["readiness"], 100)
        pending_keys = {item["key"] for item in body["verification"]["pending"]}
        self.assertIn("kyb_approved", pending_keys)
        self.assertIn("account_active", pending_keys)

    def test_ping_reports_ready_when_fully_verified(self):
        MerchantKYB.objects.create(
            merchant=self.merchant,
            decision=MerchantKYB.Decision.APPROVED,
            verified=True,
            verified_at=timezone.now(),
            source_of_funds="Product sales",
        )
        MerchantDocument.objects.create(
            merchant=self.merchant,
            document_type=MerchantDocument.Type.REGISTRATION,
            verified=True,
        )
        MerchantSettlementAccount.objects.create(
            merchant=self.merchant,
            alias_type="MOBILE",
            alias_value="+25779000000",
            currency="BIF",
            verification_status="verified",
            is_primary=True,
            is_active=True,
        )
        self.merchant.status = Merchant.Status.ACTIVE
        self.merchant.save(update_fields=["status"])

        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        body = self.client.get(self.url).json()

        self.assertTrue(body["can_operate"])
        self.assertEqual(body["verification"]["readiness"], 100)
        self.assertEqual(body["verification"]["pending"], [])
        self.assertIn("verified", body["message"].lower())
