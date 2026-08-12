import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import make_password

from apps.gateway.models import RTPRequest
from apps.payments.models import TransactionFee
from .models import (
    MerchantPlanAssignment,
    PlanExtensionOrder,
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
def create_extension_order(assignment, *, initiated_by=None):
    """
    Create a PlanExtensionOrder for the given active plan assignment.
    Raises ValueError when the plan has no extension pack defined.
    Returns the unsaved-to-gateway order (status=pending).
    """
    plan = assignment.plan
    if not plan.extension_price or not plan.extension_transactions:
        raise ValueError(
            f"Plan '{plan.name}' does not have an extension pack configured."
        )
    order = PlanExtensionOrder.objects.create(
        assignment=assignment,
        plan=plan,
        extra_transactions=plan.extension_transactions,
        amount=plan.extension_price,
        currency=plan.currency,
        status=PlanExtensionOrder.Status.PENDING,
        initiated_by=initiated_by,
    )
    return order


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
def confirm_extension_paid(order, *, provider_reference, paid_at=None):
    """Mark an extension order as paid after RTP completes."""
    from django.utils import timezone as tz
    order = PlanExtensionOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == PlanExtensionOrder.Status.PAID:
        return order
    order.status = PlanExtensionOrder.Status.PAID
    order.provider_reference = provider_reference
    order.paid_at = paid_at or tz.now()
    order.save(update_fields=["status", "provider_reference", "paid_at", "updated_at"])
    return order


def count_extension_transactions(assignment):
    """Return total extra transactions credited to this assignment via paid extensions."""
    from django.db.models import Sum
    result = PlanExtensionOrder.objects.filter(
        assignment=assignment,
        status=PlanExtensionOrder.Status.PAID,
    ).aggregate(total=Sum("extra_transactions"))
    return result["total"] or 0


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
def initiate_extension_payment(order, *, payer_alias):
    """
    Billing workflow: submit RTP to collect payment for a plan extension pack.
    """
    from apps.gateway.rtp import call_create_rtp, new_rtp_request_id, persist_rtp_request

    assignment = order.assignment
    merchant = assignment.merchant
    req_id = new_rtp_request_id(prefix="AMP-BEXT")
    payload = {
        "requestId": req_id,
        "paymentReference": order.reference,
        "payerAlias": payer_alias,
        "payerAliasType": "MOBILE",
        "merchant": {"id": merchant.merchant_code, "name": merchant.display_name},
        "order": {
            "number": order.reference,
            "description": (
                f"AmatoPay extension pack: +{order.extra_transactions} transactions "
                f"for plan {assignment.plan.name}"
            ),
        },
        "amount": str(order.amount),
        "fee": "0",
        "totalAmount": str(order.amount),
        "currency": order.currency,
    }
    result = call_create_rtp(payload)
    persist_rtp_request(
        request_id=req_id,
        payload=payload,
        result=result,
        extension_order=order,
    )
    order.provider_reference = result.get("trxRef") or result.get("providerReference", "")
    order.save(update_fields=["provider_reference", "updated_at"])
    return order


@transaction.atomic
def initiate_plan_request_payment(plan_request):
    """
    Billing workflow: submit RTP to collect payment for a plan subscription request.
    """
    from apps.gateway.rtp import call_create_rtp, new_rtp_request_id, persist_rtp_request

    merchant = plan_request.merchant
    req_id = new_rtp_request_id(prefix="AMP-PLR")
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
    result = call_create_rtp(payload)
    persist_rtp_request(
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
def apply_extension_rtp_status(order, status, data):
    """Update a billing extension order when its RTP completes or fails."""
    from .models import PlanExtensionOrder

    if status == "COMPLETED":
        confirm_extension_paid(
            order,
            provider_reference=data.get("trxRef") or data.get("providerReference", ""),
            paid_at=data.get("completedAt"),
        )
    elif status in {"REJECTED", "FAILED", "CANCELLED"}:
        PlanExtensionOrder.objects.filter(pk=order.pk).update(
            status=PlanExtensionOrder.Status.FAILED
        )


@transaction.atomic
def apply_plan_request_rtp_status(plan_request, status, data):
    """Update a billing plan request when its RTP completes or fails."""
    from .models import PlanRequest

    if status == "COMPLETED":
        plan_request.status = PlanRequest.Status.PAID
        plan_request.provider_reference = (
            data.get("trxRef") or data.get("providerReference", "")
        )
        plan_request.paid_at = data.get("completedAt") or timezone.now()
        plan_request.save(
            update_fields=["status", "provider_reference", "paid_at", "updated_at"]
        )
        activate_requested_plan(plan_request)
    elif status in {"REJECTED", "FAILED", "CANCELLED"}:
        PlanRequest.objects.filter(pk=plan_request.pk).update(
            status=PlanRequest.Status.FAILED
        )


@transaction.atomic
def apply_billing_rtp_status(rtp, status, data):
    """Dispatch an RTP status update to the correct billing workflow handler."""
    if rtp.extension_order_id:
        apply_extension_rtp_status(rtp.extension_order, status, data)
    elif rtp.plan_request_id:
        apply_plan_request_rtp_status(rtp.plan_request, status, data)


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
