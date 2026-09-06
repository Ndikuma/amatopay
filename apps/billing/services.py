import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction, models
from django.utils import timezone
from django.contrib.auth.hashers import make_password

from apps.payments.models import TransactionFee
from .models import (
    MerchantPlanAssignment,
    PricingPlan,
)


MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class FeeDecision:
    gross_amount: Decimal
    currency: str
    fee_percentage: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    fee_source: str
    pricing_plan: PricingPlan | None
    plan_assignment: MerchantPlanAssignment | None
    calculated_at: object


def active_plan_assignment(merchant, currency="BIF", *, at=None):
    from django.db.models import Q
    at = at or timezone.now()
    return (
        MerchantPlanAssignment.objects.select_related("plan")
        .filter(
            merchant=merchant,
            active=True,
            plan__active=True,
            plan__currency=currency.upper(),
            effective_from__lte=at,
        )
        .filter(Q(effective_until__isnull=True) | Q(effective_until__gt=at))
        .order_by("-effective_from", "-created_at")
        .first()
    )


def _payg_plan(currency="BIF"):
    """Return the active pay-as-you-go plan for the given currency."""
    return (
        PricingPlan.objects.filter(
            code="pay-as-you-go", active=True, currency=currency.upper()
        ).first()
    )


def resolve_transaction_fee(merchant, amount, currency="BIF", *, at=None):
    at = at or timezone.now()
    gross = Decimal(str(amount)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if gross <= 0:
        raise ValidationError({"amount": "Transaction amount must be greater than zero."})

    assignment = active_plan_assignment(merchant, currency, at=at)

    if assignment:
        # Contracted plan — fee is always 0%, plan covers the cost.
        plan = assignment.plan
        rate = plan.transaction_fee_percentage or Decimal("0")
        source = TransactionFee.Source.PRICING_PLAN
    else:
        # No contracted plan — fall back to the pay-as-you-go plan rate.
        plan = _payg_plan(currency)
        if not plan or plan.transaction_fee_percentage is None:
            raise ValidationError(
                "No active plan assignment and no pay-as-you-go plan is configured "
                f"for currency {currency.upper()}."
            )
        rate = plan.transaction_fee_percentage
        source = TransactionFee.Source.PAY_AS_YOU_GO

    rate = Decimal(rate).quantize(Decimal("0.0001"))
    fee = (gross * rate / Decimal("100")).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    net = gross - fee
    if net <= 0:
        raise ValidationError("The resolved fee must be lower than the gross amount.")
    return FeeDecision(
        gross_amount=gross,
        currency=currency.upper(),
        fee_percentage=rate,
        fee_amount=fee,
        net_amount=net,
        fee_source=source,
        pricing_plan=plan,
        plan_assignment=assignment,
        calculated_at=at,
    )


def calculate_fee(merchant, amount, currency="BIF"):
    """Compatibility helper — returns only the fee amount."""
    return resolve_transaction_fee(merchant, amount, currency).fee_amount




@transaction.atomic
def activate_requested_plan(plan_request):
    """Create a new plan assignment from a paid plan request."""
    from .models import PlanRequest

    now = timezone.now()
    plan_request = PlanRequest.objects.select_for_update().get(pk=plan_request.pk)
    if plan_request.status != PlanRequest.Status.PAID:
        raise ValueError("Plan request must be paid before activation.")

    MerchantPlanAssignment.objects.create(
        merchant=plan_request.merchant,
        plan=plan_request.plan,
        effective_from=now,
        active=True,
        reason=f"Merchant-initiated plan request {plan_request.reference}",
        assigned_by=plan_request.initiated_by,
    )
    plan_request.status = PlanRequest.Status.ACTIVE
    plan_request.save(update_fields=["status", "updated_at"])
    return plan_request






@transaction.atomic
def ensure_checkout_fee_snapshot(session):
    """Lock a checkout session and populate its fee decision only when absent."""
    locked = type(session).objects.select_for_update().get(pk=session.pk)
    if locked.fee_calculated_at and locked.fee_source:
        return locked
    decision = resolve_transaction_fee(
        locked.merchant, locked.amount, locked.currency
    )
    locked.fee_percentage = decision.fee_percentage
    locked.fee_amount = decision.fee_amount
    locked.fee_source = decision.fee_source
    locked.pricing_plan = decision.pricing_plan
    locked.plan_assignment = decision.plan_assignment
    locked.fee_calculated_at = decision.calculated_at
    locked.save(
        update_fields=[
            "fee_percentage",
            "fee_amount",
            "fee_source",
            "pricing_plan",
            "plan_assignment",
            "fee_calculated_at",
            "updated_at",
        ]
    )
    return locked




@transaction.atomic
def initiate_plan_request_payment(plan_request):
    """
    Billing workflow: submit a collection to collect payment for a plan subscription request.
    """
    from apps.gateway.collection import call_create_collection, new_collection_request_id, persist_collection_request

    merchant = plan_request.merchant
    req_id = new_collection_request_id(prefix="AMP-PLR")
    payload = {
        "requestId": req_id,
        "paymentReference": plan_request.reference,
        "payerAlias": plan_request.payer_alias,
        "payerAliasType": "MOBILE",
        "merchant": {"id": merchant.merchant_code, "name": merchant.display_name},
        "order": {
            "number": plan_request.reference,
            "description": f"AmatoPay plan subscription: {plan_request.plan.name}",
        },
        "amount": str(plan_request.amount),
        "fee": "0",
        "totalAmount": str(plan_request.amount),
        "currency": plan_request.currency,
    }
    result = call_create_collection(payload)
    persist_collection_request(
        request_id=req_id,
        payload=payload,
        result=result,
        plan_request=plan_request,
    )
    plan_request.provider_reference = (
        result.get("trxRef") or result.get("providerReference", "")
    )
    plan_request.save(update_fields=["provider_reference", "updated_at"])
    return plan_request


@transaction.atomic
def apply_billing_collection_status(collection, status, data):
    """Dispatch an collection status update to the correct billing workflow handler."""
    if collection.plan_request_id:
        apply_plan_request_collection_status(collection.plan_request, status, data)


@transaction.atomic
def create_transaction_fee_snapshot(payment):
    """Persist the payment's accepted fee decision exactly once."""
    locked_payment = type(payment).objects.select_for_update().get(pk=payment.pk)
    snapshot, created = TransactionFee.objects.get_or_create(
        transaction=locked_payment,
        defaults={
            "gross_amount": locked_payment.amount,
            "fee_percentage": locked_payment.fee_percentage,
            "fee_amount": locked_payment.fee_amount,
            "net_amount": locked_payment.net_amount,
            "fee_source": locked_payment.fee_source,
            "pricing_plan": locked_payment.pricing_plan,
            "plan_assignment": locked_payment.plan_assignment,
            "calculated_at": locked_payment.fee_calculated_at or timezone.now(),
        },
    )
    return snapshot, created
