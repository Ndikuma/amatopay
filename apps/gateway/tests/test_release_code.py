import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.contrib import admin
from django.test import TestCase
from django.utils import timezone

from apps.gateway.models import AliasVerification, GatewayRequest
from apps.gateway.services import create_payment_and_collection
from apps.gateway.release_codes import decrypt_release_code
from apps.gateway.admin import GatewayRequestAdmin
from apps.billing.models import PricingPlan
from apps.checkout.models import PaymentSession
from apps.merchants.models import Merchant


class CollectionReleaseCodeTests(TestCase):
    @patch("apps.gateway.services.client.create_collection")
    def test_collection_description_contains_hashed_six_digit_release_code(self, create_collection):
        create_collection.return_value = {
            "providerReference": "RTP-1",
            "status": "PENDING",
        }
        PricingPlan.objects.create(
            code="pay-as-you-go",
            name="Pay-as-you-go",
            currency="BIF",
            transaction_fee_percentage=Decimal("5"),
        )
        merchant = Merchant.objects.create(
            merchant_code="AMP-COLL-CODE",
            legal_name="Collection Code Test",
            display_name="Collection Code Test",
            status=Merchant.Status.ACTIVE,
        )
        session = PaymentSession.objects.create(
            merchant=merchant,
            order_number="ORDER-CODE",
            description="Consulting service",
            amount=Decimal("15000.00"),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        alias = AliasVerification.objects.create(
            request_id="ALIAS-CODE-1",
            session=session,
            alias_type="MOBILE",
            alias_value="+25779000000",
            found=True,
            status="ACTIVE",
        )

        collection = create_payment_and_collection(session, alias)

        payload = create_collection.call_args.args[0]
        match = re.search(
            r"AmatoPay release code: (\d{6})$", payload["order"]["description"]
        )
        self.assertIsNotNone(match)
        collection.payment.refresh_from_db()
        self.assertNotEqual(collection.payment.release_code_hash, match.group(1))
        self.assertTrue(check_password(match.group(1), collection.payment.release_code_hash))
        self.assertNotEqual(collection.release_code_ciphertext, match.group(1))
        self.assertEqual(decrypt_release_code(collection.release_code_ciphertext), match.group(1))
        rendered = str(GatewayRequestAdmin(GatewayRequest, admin.site).secure_delivery_code(collection))
        self.assertIn(f'value="{match.group(1)}"', rendered)
        self.assertIn("navigator.clipboard.writeText", rendered)
        self.assertNotIn(collection.release_code_ciphertext, rendered)
        self.assertNotIn(match.group(1), str(collection.raw_request))
        self.assertIn("[REDACTED]", collection.raw_request["order"]["description"])
