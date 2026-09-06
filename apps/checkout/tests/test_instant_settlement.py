from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.checkout.models import PaymentSession
from apps.checkout.serializers import PaymentSessionSerializer
from apps.deliveries.models import DeliveryConfirmation
from apps.fiduciary.models import FiduciaryAccount
from apps.merchants.models import Merchant, MerchantSettlementAccount
from apps.payments.models import Payment, PaymentStatusHistory
from apps.payments.services import apply_payment_collection_status
from apps.webhooks.models import WebhookEvent


class _Req:
    def __init__(self, merchant):
        self.merchant = merchant


class InstantSettlementSerializerTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-INSTANT-1", legal_name="Bus Co", display_name="Bus Co",
            status=Merchant.Status.ACTIVE,
        )

    def _payload(self, **over):
        base = {
            "order_number": "BK-1", "description": "Bus ticket BK-1",
            "amount": "10000.00", "currency": "BIF", "payer_alias": "+25779000000",
            "require_delivery_confirmation": False,
        }
        base.update(over)
        return base

    def test_instant_session_rejected_when_merchant_not_enabled(self):
        s = PaymentSessionSerializer(data=self._payload(), context={"request": _Req(self.merchant)})
        self.assertFalse(s.is_valid())
        self.assertIn("require_delivery_confirmation", s.errors)

    def test_instant_session_allowed_when_merchant_enabled(self):
        self.merchant.instant_settlement_enabled = True
        self.merchant.save(update_fields=["instant_settlement_enabled"])
        s = PaymentSessionSerializer(data=self._payload(), context={"request": _Req(self.merchant)})
        self.assertTrue(s.is_valid(), s.errors)

    def test_protected_session_needs_no_capability(self):
        s = PaymentSessionSerializer(
            data=self._payload(require_delivery_confirmation=True),
            context={"request": _Req(self.merchant)},
        )
        self.assertTrue(s.is_valid(), s.errors)


class InstantSettlementFlowTests(TestCase):
    databases = {"default", "security"}

    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-INSTANT-2", legal_name="Bus Co", display_name="Bus Co",
            status=Merchant.Status.ACTIVE, instant_settlement_enabled=True,
        )
        MerchantSettlementAccount.objects.create(
            merchant=self.merchant, alias_type="MOBILE", alias_value="+25768000000",
            account_name="Bus Co", currency="BIF", verification_status="verified",
            is_primary=True, is_active=True,
        )
        FiduciaryAccount.objects.create(
            account_number="FID-INSTANT", account_name="Fiduciary", currency="BIF",
            active=True, verified_at=timezone.now(),
        )
        self.session = PaymentSession.objects.create(
            merchant=self.merchant, order_number="BK-9", description="Bus ticket BK-9",
            amount=Decimal("10000.00"), require_delivery_confirmation=False,
            expires_at=timezone.now() + timedelta(hours=1),
            status=PaymentSession.Status.AWAITING_PAYMENT,
        )
        self.payment = Payment.objects.create(
            session=self.session, merchant=self.merchant, amount=self.session.amount,
            payer_alias="+25779001111", status=Payment.Status.PROCESSING,
        )

    @patch("apps.deliveries.services.start_merchant_payout")
    def test_completed_collection_auto_settles(self, payout):
        with self.captureOnCommitCallbacks(execute=True):
            apply_payment_collection_status(
                self.payment, "COMPLETED",
                {"trxRef": "T-1", "status": "COMPLETED"},
            )

        self.payment.refresh_from_db()
        self.assertIsNotNone(self.payment.release_code_confirmed_at)
        self.assertEqual(self.payment.release_code_hash, "")
        self.assertEqual(self.payment.status, Payment.Status.RELEASE_PENDING)
        self.assertEqual(
            self.payment.delivery.confirmation.method,
            DeliveryConfirmation.Method.INSTANT_SETTLEMENT,
        )
        payout.assert_called_once()

        types = set(
            WebhookEvent.objects.filter(merchant=self.merchant).values_list("type", flat=True)
        )
        self.assertIn("payment.paid", types)
        self.assertIn("delivery.confirmed", types)
        paid = WebhookEvent.objects.get(merchant=self.merchant, type="payment.paid")
        self.assertTrue(paid.payload["data"]["instant_settlement"])
