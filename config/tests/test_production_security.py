from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.checkout.models import PaymentSession
from apps.merchants.models import Merchant, MerchantApiKey
from apps.payments.models import Payment
from apps.settlements.models import Settlement


class ProductionApiSecurityTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-SECURE-1",
            legal_name="Secure One",
            display_name="Secure One",
            status=Merchant.Status.ACTIVE,
        )
        self.other_merchant = Merchant.objects.create(
            merchant_code="AMP-SECURE-2",
            legal_name="Secure Two",
            display_name="Secure Two",
            status=Merchant.Status.ACTIVE,
        )
        _, self.raw_key = MerchantApiKey.issue(self.merchant, "Security test")
        self.client = APIClient()

    def payment_for(self, merchant, order):
        session = PaymentSession.objects.create(
            merchant=merchant,
            order_number=order,
            description="Security test",
            amount=Decimal("10000.00"),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        return Payment.objects.create(
            merchant=merchant,
            session=session,
            amount=session.amount,
            fee_amount=Decimal("300.00"),
            fee_percentage=Decimal("3.0000"),
        )

    def test_internal_operations_apis_are_not_exposed(self):
        user = get_user_model().objects.create_user(
            username="ordinary-user", password="safe-test-password-2026"
        )
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.get("/api/v1/merchants/").status_code, 404)
        self.assertEqual(
            self.client.get("/api/v1/compliance/suspicious-transactions/").status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/v1/fiduciary/holds/").status_code, 404)

    def test_staff_also_uses_unfold_not_operations_api(self):
        staff = get_user_model().objects.create_user(
            username="operations", password="safe-test-password-2026", is_staff=True
        )
        self.client.force_authenticate(user=staff)
        self.assertEqual(self.client.get("/api/v1/merchants/").status_code, 404)

    def test_non_active_merchant_key_can_ping_but_not_transact(self):
        pending = Merchant.objects.create(
            merchant_code="AMP-PENDING-1",
            legal_name="Pending SA",
            display_name="Pending",
            status=Merchant.Status.PENDING_KYB,
        )
        _, raw = MerchantApiKey.issue(pending, "Pending key")
        self.client.credentials(HTTP_X_API_KEY=raw)

        self.assertEqual(self.client.get("/api/v1/ping/").status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/checkout/alias-verifications/?payer_alias=x").status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/v1/checkout/sessions/", {}, format="json").status_code,
            403,
        )

    def test_settlement_api_is_not_exposed(self):
        own_payment = self.payment_for(self.merchant, "OWN")
        Settlement.objects.create(
            merchant=self.merchant,
            payment=own_payment,
            gross_amount=own_payment.amount,
            merchant_fee=own_payment.fee_amount,
            net_amount=own_payment.net_amount,
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

        # Merchants review settlements in their dashboard, not via the API.
        self.assertEqual(self.client.get("/api/v1/settlements/items/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/settlements/").status_code, 404)

    def test_refund_api_is_not_exposed(self):
        other_payment = self.payment_for(self.other_merchant, "OTHER-REFUND")
        other_payment.status = Payment.Status.DELIVERY_PENDING
        other_payment.save(update_fields=["status", "updated_at"])
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

        response = self.client.post(
            "/api/v1/refunds/",
            {
                "payment": str(other_payment.id),
                "amount": "500.00",
                "reason": "order_cancelled",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_health_endpoints_are_public(self):
        self.assertEqual(self.client.get("/health/live/").status_code, 200)
        self.assertEqual(self.client.get("/health/ready/").status_code, 200)
