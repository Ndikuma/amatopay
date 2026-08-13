from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from apps.merchants.models import (
    Merchant,
    MerchantActivity,
    MerchantSettlementAccount,
    MerchantWebhookEndpoint,
)
from apps.webhooks.models import WebhookDelivery
from apps.checkout.models import PaymentSession
from apps.payments.models import Payment, PaymentStatusHistory
from apps.refunds.models import Refund
from apps.billing.models import MerchantPlanAssignment, PricingPlan


class PortalAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner", email="owner@example.bi", password="safe-test-pass-2026"
        )
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-TEST-1",
            legal_name="Test Merchant",
            display_name="Test Merchant",
            status="active",
            owner=self.user,
        )

    def test_public_pages_are_available(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "Start an investigation")
        self.assertContains(home, "funds stay protected")
        self.assertContains(home, 'href="/deliveries/"')
        self.assertEqual(self.client.get("/developers/").status_code, 200)
        self.assertEqual(self.client.get("/account/sign-in/").status_code, 200)

    def test_private_workspace_redirects_to_merchant_login(self):
        response = self.client.get("/dashboard/billing/")
        self.assertRedirects(response, "/account/sign-in/?next=/dashboard/")

    def test_login_is_recorded_for_direct_merchant_owner(self):
        self.client.login(username="owner", password="safe-test-pass-2026")
        self.assertTrue(
            MerchantActivity.objects.filter(
                merchant=self.merchant, action="account.login"
            ).exists()
        )
        self.assertEqual(self.client.get("/dashboard/profile/").status_code, 200)
        self.assertEqual(self.client.get("/dashboard/team/").status_code, 404)

    def test_owner_can_access_business_and_financial_pages(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/dashboard/developers/").status_code, 200)
        self.assertEqual(self.client.get("/dashboard/settlements/").status_code, 200)

    def test_billing_page_shows_pay_as_you_go_pricing(self):
        self.client.force_login(self.user)

        response = self.client.get("/dashboard/billing/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pay as you go")
        self.assertContains(response, "3.00%")
        self.assertContains(response, 'href="/dashboard/billing/"', html=False)

    def test_billing_page_shows_assigned_plan_price_and_allowance(self):
        plan = PricingPlan.objects.create(
            code="dashboard-growth",
            name="Growth",
            monthly_price=Decimal("150000.00"),
            included_transactions_per_month=2500,
        )
        MerchantPlanAssignment.objects.create(
            merchant=self.merchant,
            plan=plan,
            effective_from=timezone.now() - timedelta(days=1),
            reason="Signed growth contract",
            contracted_monthly_price=Decimal("125000.00"),
            contracted_transactions_per_month=3000,
        )
        self.client.force_login(self.user)

        response = self.client.get("/dashboard/billing/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Growth")
        self.assertContains(response, "125000")
        self.assertContains(response, "3000")
        self.assertContains(response, "0% transaction fee")

    def test_owner_can_fill_missing_profile_value_once_but_not_update_it(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/dashboard/profile/",
            {"registration_number": "RC-OWNER-1"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.registration_number, "RC-OWNER-1")

        self.client.post(
            "/dashboard/profile/", {"registration_number": "RC-CHANGED"}
        )
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.registration_number, "RC-OWNER-1")
        self.assertContains(
            self.client.get("/dashboard/profile/"), "Contact AmatoPay Support"
        )

    def test_trust_page_explains_complete_protection_timeline(self):
        self.client.force_login(self.user)

        response = self.client.get("/dashboard/trust/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payer alias verified")
        self.assertContains(response, "Payment authenticated")
        self.assertContains(response, "Funds protected")
        self.assertContains(response, "Delivery confirmed")
        self.assertContains(response, "Funds released")
        self.assertContains(response, "six-digit secure code")

    def test_owner_configures_and_tests_webhook_from_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/dashboard/developers/webhooks/create/",
            {
                "url": "https://merchant.example/webhooks/amatopay",
                "description": "Production backend",
                "events": ["payment.paid", "settlement.completed"],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        endpoint = MerchantWebhookEndpoint.objects.get(merchant=self.merchant)
        self.assertTrue(endpoint.secret.startswith("whsec_"))
        self.assertContains(response, endpoint.secret)
        self.assertContains(response, "Production backend")

        response = self.client.post(
            f"/dashboard/developers/webhooks/{endpoint.id}/test/", follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(WebhookDelivery.objects.filter(endpoint=endpoint).exists())

        self.client.post(f"/dashboard/developers/webhooks/{endpoint.id}/toggle/")
        endpoint.refresh_from_db()
        self.assertFalse(endpoint.active)

    def test_webhook_management_api_is_not_exposed(self):
        self.assertEqual(self.client.get("/api/v1/webhook-endpoints/").status_code, 404)

    def _payment(self, status=Payment.Status.FUNDS_HELD):
        session = PaymentSession.objects.create(
            merchant=self.merchant,
            order_number="ORDER-PORTAL-1",
            description="Portal workflow test",
            amount=Decimal("100000.00"),
            fee_amount=Decimal("2000.00"),
            payer_alias="+25779000000",
            expires_at=timezone.now() + timedelta(hours=3),
        )
        return Payment.objects.create(
            session=session,
            merchant=self.merchant,
            amount=Decimal("100000.00"),
            fee_amount=Decimal("2000.00"),
            payer_alias="+25779000000",
            currency="BIF",
            status=status,
        )

    def test_refunds_are_read_only_in_merchant_dashboard(self):
        payment = self._payment(Payment.Status.PAID)
        Refund.objects.create(
            payment=payment,
            amount=Decimal("25000"),
            reason=Refund.Reason.ORDER_CANCELLED,
            status=Refund.Status.PROCESSING,
            requested_by="operations",
        )
        self.client.force_login(self.user)
        response = self.client.get("/dashboard/refunds/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Refund controls are managed by AmatoPay")
        self.assertNotContains(response, "Submit refund request")
        self.assertEqual(self.client.post("/dashboard/refunds/create/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/refunds/").status_code, 404)

    def test_claims_are_not_merchant_facing(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/dashboard/claims/").status_code, 404)
        self.assertEqual(self.client.post("/dashboard/claims/create/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/claims/cases/").status_code, 404)

    def test_payment_detail_shows_timeline_and_delivery_verification(self):
        payment = self._payment(Payment.Status.DELIVERY_PENDING)
        MerchantSettlementAccount.objects.create(
            merchant=self.merchant,
            alias_value="+25768000000",
            account_name="Test Merchant",
            verification_status="verified",
            is_primary=True,
            is_active=True,
        )
        payment.release_code_hash = make_password("482731")
        payment.save(update_fields=["release_code_hash", "updated_at"])
        PaymentStatusHistory.objects.create(payment=payment, status="paid")
        PaymentStatusHistory.objects.create(
            payment=payment, status="delivery_pending"
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/dashboard/payments/{payment.reference}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Status timeline")
        self.assertContains(response, "Secure delivery code")
        self.assertContains(response, payment.reference)
        self.assertContains(response, "+25768000000")
        self.assertContains(
            response,
            f"/deliveries/{payment.reference}/",
        )
        self.assertNotContains(response, "482731")

    def test_delivery_form_rejects_a_mismatched_payment_reference(self):
        payment = self._payment(Payment.Status.DELIVERY_PENDING)
        payment.release_code_hash = make_password("482731")
        payment.save(update_fields=["release_code_hash", "updated_at"])
        self.client.force_login(self.user)

        response = self.client.post(
            f"/dashboard/payments/{payment.reference}/confirm-delivery/",
            {"payment_reference": "AMP-PAY-WRONG", "secure_code": "482731"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Payment reference does not match this payment.",
            status_code=400,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.release_code_failed_attempts, 0)
