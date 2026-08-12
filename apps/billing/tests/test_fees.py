from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import MerchantPlanAssignment, PricingPlan
from apps.billing.services import (
    create_transaction_fee_snapshot,
    resolve_transaction_fee,
)
from apps.gateway.models import P2PRequest
from apps.gateway.services import apply_p2p_status
from apps.checkout.models import PaymentSession
from apps.fiduciary.models import FiduciaryAccount, FiduciaryEntry, FundHold
from apps.fiduciary.services import create_settlement_from_hold
from apps.merchants.models import Merchant, MerchantApiKey
from apps.payments.models import Payment, TransactionFee


def _make_payg_plan(currency="BIF", rate="5.0000"):
    plan, _ = PricingPlan.objects.get_or_create(
        code="pay-as-you-go",
        defaults={
            "name": "Pay-as-you-go",
            "monthly_price": 0,
            "included_transactions_per_month": 0,
            "transaction_fee_percentage": Decimal(rate),
            "currency": currency,
            "active": True,
        },
    )
    return plan


class FeeWorkflowTests(TestCase):
    amount = Decimal("100000.00")

    def setUp(self):
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user(
            username="fee-approver", password="safe-test-password-2026"
        )
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-FEE-TEST",
            legal_name="Fee Test Merchant",
            display_name="Fee Test Merchant",
            status=Merchant.Status.ACTIVE,
        )
        self.payg = _make_payg_plan()

    def _create_payment_snapshot(self, decision=None, order="FEE-ORDER"):
        decision = decision or resolve_transaction_fee(self.merchant, self.amount)
        session = PaymentSession.objects.create(
            merchant=self.merchant,
            order_number=order,
            description="Fee workflow test",
            amount=decision.gross_amount,
            fee_percentage=decision.fee_percentage,
            fee_amount=decision.fee_amount,
            fee_source=decision.fee_source,
            pricing_plan=decision.pricing_plan,
            plan_assignment=decision.plan_assignment,
            fee_calculated_at=decision.calculated_at,
            expires_at=self.now + timedelta(hours=1),
        )
        payment = Payment.objects.create(
            merchant=self.merchant,
            session=session,
            amount=session.amount,
            fee_percentage=session.fee_percentage,
            fee_amount=session.fee_amount,
            fee_source=session.fee_source,
            pricing_plan=session.pricing_plan,
            plan_assignment=session.plan_assignment,
            fee_calculated_at=session.fee_calculated_at,
        )
        snapshot, _ = create_transaction_fee_snapshot(payment)
        return payment, snapshot

    # ── PAYG fallback ────────────────────────────────────────────────────────

    def test_unassigned_merchant_uses_payg_plan_rate(self):
        decision = resolve_transaction_fee(self.merchant, self.amount)
        self.assertEqual(decision.fee_percentage, Decimal("5.0000"))
        self.assertEqual(decision.fee_amount, Decimal("5000.00"))
        self.assertEqual(decision.net_amount, Decimal("95000.00"))
        self.assertEqual(decision.fee_source, "PAY_AS_YOU_GO")
        self.assertEqual(decision.pricing_plan, self.payg)
        self.assertIsNone(decision.plan_assignment)

    def test_no_payg_plan_raises_validation_error(self):
        self.payg.active = False
        self.payg.save(update_fields=["active"])
        with self.assertRaises(ValidationError):
            resolve_transaction_fee(self.merchant, self.amount)

    # ── Contracted plan ──────────────────────────────────────────────────────

    def test_contracted_plan_has_zero_transaction_fee(self):
        plan = PricingPlan.objects.create(
            code="business",
            name="Business",
            monthly_price=Decimal("850000.00"),
            included_transactions_per_month=544,
            currency="BIF",
            active=True,
        )
        assignment = MerchantPlanAssignment.objects.create(
            merchant=self.merchant,
            plan=plan,
            effective_from=self.now - timedelta(minutes=1),
            reason="Business contract",
            assigned_by=self.user,
        )
        decision = resolve_transaction_fee(self.merchant, self.amount)
        self.assertEqual(decision.fee_percentage, Decimal("0.0000"))
        self.assertEqual(decision.fee_amount, Decimal("0.00"))
        self.assertEqual(decision.net_amount, self.amount)
        self.assertEqual(decision.fee_source, "PRICING_PLAN")
        self.assertEqual(decision.pricing_plan, plan)
        self.assertEqual(decision.plan_assignment, assignment)

    def test_expired_plan_assignment_falls_back_to_payg(self):
        plan = PricingPlan.objects.create(
            code="starter", name="Starter",
            monthly_price=Decimal("250000.00"),
            included_transactions_per_month=160,
            currency="BIF", active=True,
        )
        MerchantPlanAssignment.objects.create(
            merchant=self.merchant,
            plan=plan,
            effective_from=self.now - timedelta(days=10),
            effective_until=self.now - timedelta(days=1),
            reason="Expired contract",
            assigned_by=self.user,
        )
        decision = resolve_transaction_fee(self.merchant, self.amount)
        self.assertEqual(decision.fee_source, "PAY_AS_YOU_GO")

    def test_contracted_monthly_price_and_limit_override(self):
        plan = PricingPlan.objects.create(
            code="premium", name="Premium",
            monthly_price=Decimal("1500000.00"),
            included_transactions_per_month=960,
            currency="BIF", active=True,
        )
        assignment = MerchantPlanAssignment.objects.create(
            merchant=self.merchant,
            plan=plan,
            effective_from=self.now - timedelta(minutes=1),
            reason="Premium contract",
            assigned_by=self.user,
            contracted_transactions_per_month=1200,
            contracted_monthly_price=Decimal("1400000.00"),
        )
        self.assertEqual(assignment.monthly_transaction_limit, 1200)
        self.assertEqual(assignment.effective_monthly_price, Decimal("1400000.00"))

    # ── Fee snapshot ─────────────────────────────────────────────────────────

    def test_fee_snapshot_is_immutable(self):
        _, snapshot = self._create_payment_snapshot()
        with self.assertRaises(ValidationError):
            TransactionFee.objects.filter(pk=snapshot.pk).update(fee_amount=0)
        with self.assertRaises(ValidationError):
            TransactionFee.objects.filter(pk=snapshot.pk).delete()

    def test_fee_snapshot_creation_is_idempotent(self):
        payment, first = self._create_payment_snapshot()
        second, created = create_transaction_fee_snapshot(payment)
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TransactionFee.objects.filter(transaction=payment).count(), 1)

    def test_snapshot_preserves_rate_at_time_of_payment(self):
        decision = resolve_transaction_fee(self.merchant, self.amount)
        _, snapshot = self._create_payment_snapshot(decision)
        # Change PAYG rate after snapshot
        self.payg.transaction_fee_percentage = Decimal("10.0000")
        self.payg.save(update_fields=["transaction_fee_percentage"])
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.fee_percentage, Decimal("5.0000"))

    # ── Rounding ─────────────────────────────────────────────────────────────

    def test_bif_rounding_uses_decimal_half_up(self):
        decision = resolve_transaction_fee(self.merchant, Decimal("100.50"))
        # 5% of 100.50 = 5.025 → rounds to 5.03
        self.assertEqual(decision.fee_amount, Decimal("5.03"))
        self.assertEqual(decision.net_amount, Decimal("95.47"))

    # ── Settlement accounting ────────────────────────────────────────────────

    def test_settlement_uses_snapshot_net_amount(self):
        payment, snapshot = self._create_payment_snapshot()
        payment.status = Payment.Status.RELEASE_PENDING
        payment.save(update_fields=["status", "updated_at"])
        account = FiduciaryAccount.objects.create(
            account_number="FEE-FIDUCIARY", currency="BIF"
        )
        hold = FundHold.objects.create(
            payment=payment,
            fiduciary_account=account,
            amount=payment.amount,
            status=FundHold.Status.RELEASE_PENDING,
        )
        settlement = create_settlement_from_hold(hold)
        self.assertEqual(settlement.gross_amount, snapshot.gross_amount)
        self.assertEqual(settlement.merchant_fee, snapshot.fee_amount)
        self.assertEqual(settlement.net_amount, snapshot.net_amount)

        p2p = P2PRequest.objects.create(
            request_id="P2P-FEE-SNAPSHOT",
            settlement=settlement,
            provider_reference="P2P-FEE-PROVIDER",
            status="processing",
        )
        apply_p2p_status({
            "eventId": "P2P-FEE-COMPLETED",
            "settlementReference": settlement.reference,
            "paymentReference": payment.reference,
            "providerReference": p2p.provider_reference,
            "status": "COMPLETED",
        })
        debits = FiduciaryEntry.objects.filter(
            payment=payment, direction=FiduciaryEntry.Direction.DEBIT
        )
        self.assertEqual(debits.filter(kind=FiduciaryEntry.Kind.FEE).count(), 1)
        self.assertEqual(debits.filter(kind=FiduciaryEntry.Kind.RELEASE).count(), 1)
        self.assertEqual(
            sum(debits.values_list("amount", flat=True)), snapshot.gross_amount
        )

    # ── API ──────────────────────────────────────────────────────────────────

    @patch("apps.gateway.services.client.create_rtp")
    @patch("apps.gateway.services.client.verify_alias")
    def test_api_cannot_manipulate_server_fee_fields(self, verify_alias, create_rtp):
        verify_alias.return_value = {
            "found": True, "status": "ACTIVE",
            "customer": {"name": "Fee Payer", "reference": "payer-1"},
            "account": {"type": "MOBILE", "currency": "BIF"},
        }
        create_rtp.return_value = {"providerReference": "RTP-FEE", "status": "PENDING"}
        _, raw_key = MerchantApiKey.issue(self.merchant, "Fee API")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)
        response = client.post(
            "/api/v1/checkout/sessions/",
            {
                "order_number": "UNTRUSTED-FEE",
                "description": "Fee manipulation test",
                "amount": "100000.00",
                "currency": "BIF",
                "payer_alias": "+25779000000",
                "fee_percentage": "0.00",
                "fee_amount": "0.00",
                "fee_source": "UNTRUSTED_CLIENT_VALUE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        session = PaymentSession.objects.get(session_id=response.json()["session_id"])
        self.assertEqual(session.fee_percentage, Decimal("5.0000"))
        self.assertEqual(session.fee_amount, Decimal("5000.00"))
        self.assertEqual(session.fee_source, "PAY_AS_YOU_GO")

    def test_quote_api_returns_payg_fee(self):
        _, raw_key = MerchantApiKey.issue(self.merchant, "Quote API")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)
        response = client.get("/api/v1/fees/quote/?amount=100000&currency=BIF")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["fee_rate"], "5.00")
        self.assertEqual(data["fee_amount"], "5000.00")
        self.assertEqual(data["fee_source"], "PAY_AS_YOU_GO")
        self.assertEqual(data["pricing_plan"], "pay-as-you-go")
