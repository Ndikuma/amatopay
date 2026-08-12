from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import PaymentSession
from apps.fiduciary.models import FiduciaryAccount, FundHold
from apps.gateway.models import RTPRequest
from apps.merchants.models import Merchant, MerchantApiKey, MerchantSettlementAccount
from apps.payments.models import Payment
from apps.deliveries.models import ProtectionClaim


class SecureDeliveryConfirmationTests(TestCase):
    code = "482731"

    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-DELIVERY-TEST",
            legal_name="Delivery Test",
            display_name="Delivery Test",
            status=Merchant.Status.ACTIVE,
        )
        _, raw_key = MerchantApiKey.issue(self.merchant, "Delivery API")
        MerchantSettlementAccount.objects.create(
            merchant=self.merchant,
            alias_type="MOBILE",
            alias_value="+25768000000",
            account_name="Delivery Test",
            currency="BIF",
            verification_status="verified",
            is_primary=True,
            is_active=True,
        )
        session = PaymentSession.objects.create(
            merchant=self.merchant,
            order_number="ORDER-1",
            description="Test service",
            amount="10000.00",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.payment = Payment.objects.create(
            session=session,
            merchant=self.merchant,
            amount=session.amount,
            payer_alias="+25779001111",
            status=Payment.Status.DELIVERY_PENDING,
            release_code_hash=make_password(self.code),
        )
        account = FiduciaryAccount.objects.create(
            account_number="FID-1", account_name="Fiduciary", currency="BIF"
        )
        FundHold.objects.create(
            payment=self.payment,
            fiduciary_account=account,
            amount=self.payment.amount,
            status=FundHold.Status.DELIVERY_PENDING,
            release_eligible_at=timezone.now() + timedelta(days=4),
        )
        RTPRequest.objects.create(
            request_id="RTP-DELIVERY-TEST",
            payment=self.payment,
            provider_reference="RTP-DELIVERY-REF",
            release_code_ciphertext="encrypted-test-code",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_X_API_KEY=raw_key)
        self.url = f"/api/v1/payments/{self.payment.reference}/confirm-delivery/"

    @patch("apps.deliveries.services.start_merchant_payout")
    def test_correct_code_confirms_delivery_and_starts_release(self, payout):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                {"secure_code": self.code},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["delivery_confirmed"])
        self.payment.refresh_from_db()
        self.assertIsNotNone(self.payment.release_code_confirmed_at)
        self.assertEqual(self.payment.release_code_hash, "")
        self.assertEqual(self.payment.rtp.release_code_ciphertext, "")
        self.assertEqual(self.payment.status, Payment.Status.RELEASE_PENDING)
        self.assertEqual(self.payment.delivery.status, "delivered")
        self.assertEqual(
            self.payment.delivery.confirmation.confirmed_by, "payer_secure_code"
        )
        payout.assert_called_once()

    def test_wrong_code_is_rejected_and_attempt_is_recorded(self):
        response = self.client.post(self.url, {"secure_code": "000000"}, format="json")

        self.assertEqual(response.status_code, 403)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.release_code_failed_attempts, 1)
        self.assertFalse(hasattr(self.payment, "delivery"))

    def test_code_must_have_exactly_six_digits(self):
        response = self.client.post(self.url, {"secure_code": "12345A"}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_merchant_cannot_confirm_another_merchants_payment(self):
        other = Merchant.objects.create(
            merchant_code="AMP-OTHER",
            legal_name="Other Merchant",
            display_name="Other Merchant",
            status=Merchant.Status.ACTIVE,
        )
        _, other_key = MerchantApiKey.issue(other, "Other API")
        self.client.credentials(HTTP_X_API_KEY=other_key)

        response = self.client.post(self.url, {"secure_code": self.code}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_customer_can_open_public_delivery_page(self):
        response = self.client.get(f"/deliveries/{self.payment.reference}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm your delivery")
        self.assertContains(response, "I did not receive it or there is a problem")
        self.assertContains(response, "four business days")
        self.assertContains(response, "Protection deadline")
        self.assertContains(response, "/static/checkout/css/delivery.css")

    def test_customer_can_find_payment_from_public_lookup(self):
        lookup = self.client.get("/deliveries/")
        self.assertContains(lookup, "/static/checkout/css/delivery.css")
        response = self.client.post(
            "/deliveries/", {"payment_reference": self.payment.reference}
        )

        self.assertRedirects(
            response,
            f"/deliveries/{self.payment.reference}/",
            fetch_redirect_response=False,
        )

    def test_cancelled_payment_shows_clear_unavailable_page(self):
        self.payment.status = Payment.Status.CANCELLED
        self.payment.save(update_fields=["status"])

        response = self.client.get(f"/deliveries/{self.payment.reference}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delivery decision unavailable")
        self.assertContains(response, "This payment is cancelled")
        self.assertNotContains(response, "Submit securely")

    def test_lookup_does_not_redirect_to_cancelled_payment(self):
        self.payment.status = Payment.Status.CANCELLED
        self.payment.save(update_fields=["status"])

        response = self.client.post(
            "/deliveries/", {"payment_reference": self.payment.reference}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not find an eligible protected payment")

    @patch("apps.deliveries.services.start_merchant_payout")
    def test_customer_can_confirm_delivery_publicly(self, payout):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/deliveries/{self.payment.reference}/",
                {"decision": "confirm", "secure_code": self.code},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delivery confirmed")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.RELEASE_PENDING)
        payout.assert_called_once()

    def test_customer_report_starts_investigation_and_freezes_funds(self):
        response = self.client.post(
            f"/deliveries/{self.payment.reference}/",
            {
                "decision": "report",
                "secure_code": self.code,
                "reason": "not_received",
                "description": "The service was never provided.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Investigation open")
        self.payment.refresh_from_db()
        self.payment.fund_hold.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.DISPUTED)
        self.assertEqual(self.payment.fund_hold.status, FundHold.Status.DISPUTED)
        self.assertEqual(self.payment.release_code_hash, "")
        claim = ProtectionClaim.objects.get(payment=self.payment)
        self.assertEqual(claim.opened_by, "payer_public_portal:payer_secure_code")
        self.assertEqual(claim.reason, "not_received")
        self.assertEqual(claim.events.count(), 1)

    def test_wrong_public_code_is_recorded_without_opening_claim(self):
        response = self.client.post(
            f"/deliveries/{self.payment.reference}/",
            {
                "decision": "report",
                "secure_code": "000000",
                "reason": "not_received",
                "description": "The service was never provided.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.release_code_failed_attempts, 1)
        self.assertFalse(ProtectionClaim.objects.filter(payment=self.payment).exists())

    @override_settings(MEDIA_ROOT="/tmp/amatopay-delivery-test-media")
    def test_customer_without_code_can_request_review_with_alias_and_evidence(self):
        response = self.client.post(
            f"/deliveries/{self.payment.reference}/",
            {
                "decision": "review",
                "payer_alias": "+257 7900 1111",
                "proof_method": "receipt_or_invoice",
                "description": "I received the service but the release code never arrived.",
                "evidence_file": SimpleUploadedFile(
                    "receipt.txt", b"customer receipt", content_type="text/plain"
                ),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Investigation open")
        claim = ProtectionClaim.objects.get(payment=self.payment)
        self.assertEqual(claim.reason, "alternative_proof:receipt_or_invoice")
        self.assertEqual(
            claim.opened_by, "payer_public_portal:verified_payer_alias"
        )
        self.assertEqual(claim.evidence_items.count(), 1)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.DISPUTED)
        self.assertEqual(self.payment.delivery.status, "under_review")
        self.assertEqual(self.payment.delivery.confirmation.decision, "review")

    def test_customer_without_code_cannot_use_wrong_payer_alias(self):
        response = self.client.post(
            f"/deliveries/{self.payment.reference}/",
            {
                "decision": "review",
                "payer_alias": "+25700000000",
                "proof_method": "receipt_or_invoice",
                "description": "Please review this delivery.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "payer alias does not match", html=False)
        self.assertFalse(ProtectionClaim.objects.filter(payment=self.payment).exists())

    def test_merchant_can_open_delivery_review_with_alias(self):
        response = self.client.post(
            f"/api/v1/payments/{self.payment.reference}/delivery-review/",
            {
                "payer_alias": "+257 7900 1111",
                "proof_method": "signed_delivery_note",
                "description": "Customer signed delivery note but has no code.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["review_opened"])
        claim = ProtectionClaim.objects.get(payment=self.payment)
        self.assertEqual(claim.reason, "alternative_proof:signed_delivery_note")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.DISPUTED)
        self.assertEqual(self.payment.delivery.status, "under_review")
        self.assertEqual(self.payment.delivery.confirmation.decision, "review")

    def test_merchant_delivery_review_with_wrong_alias_is_rejected(self):
        response = self.client.post(
            f"/api/v1/payments/{self.payment.reference}/delivery-review/",
            {
                "payer_alias": "+25700000000",
                "proof_method": "signed_delivery_note",
                "description": "Customer signed delivery note but has no code.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ProtectionClaim.objects.filter(payment=self.payment).exists())
