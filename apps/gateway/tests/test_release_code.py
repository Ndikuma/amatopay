import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.contrib import admin
from django.test import TestCase
from django.utils import timezone

from apps.gateway.models import AliasVerification, RTPRequest
from apps.gateway.services import create_payment_and_rtp
from apps.gateway.release_codes import decrypt_release_code
from apps.gateway.admin import RTPRequestAdmin
from apps.checkout.models import PaymentSession
from apps.merchants.models import Merchant


class RTPReleaseCodeTests(TestCase):
    @patch("apps.gateway.services.client.create_rtp")
    def test_rtp_description_contains_hashed_six_digit_release_code(self, create_rtp):
        create_rtp.return_value = {
            "providerReference": "RTP-1",
            "status": "PENDING",
        }
        merchant = Merchant.objects.create(
            merchant_code="AMP-RTP-CODE",
            legal_name="RTP Code Test",
            display_name="RTP Code Test",
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

        rtp = create_payment_and_rtp(session, alias)

        payload = create_rtp.call_args.args[0]
        match = re.search(
            r"AmatoPay release code: (\d{6})$", payload["order"]["description"]
        )
        self.assertIsNotNone(match)
        rtp.payment.refresh_from_db()
        self.assertNotEqual(rtp.payment.release_code_hash, match.group(1))
        self.assertTrue(check_password(match.group(1), rtp.payment.release_code_hash))
        self.assertNotEqual(rtp.release_code_ciphertext, match.group(1))
        self.assertEqual(decrypt_release_code(rtp.release_code_ciphertext), match.group(1))
        rendered = str(RTPRequestAdmin(RTPRequest, admin.site).secure_delivery_code(rtp))
        self.assertIn(f'value="{match.group(1)}"', rendered)
        self.assertIn("navigator.clipboard.writeText", rendered)
        self.assertNotIn(rtp.release_code_ciphertext, rendered)
        self.assertNotIn(match.group(1), str(rtp.raw_request))
        self.assertIn("[REDACTED]", rtp.raw_request["order"]["description"])
