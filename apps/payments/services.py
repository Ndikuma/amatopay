import secrets

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from apps.billing.services import (
    create_transaction_fee_snapshot,
    ensure_checkout_fee_snapshot,
)
from apps.checkout.models import PaymentSession
from apps.gateway.rtp import (
    call_create_rtp,
    new_rtp_request_id,
    persist_rtp_request,
)
from apps.webhooks.services import emit_event

from .models import Payment, PaymentStatusHistory


@transaction.atomic
def initiate_payment(session):
    """Ensure fee snapshot and create a Payment record for a checkout session."""
    session = ensure_checkout_fee_snapshot(session)
    payment, created = Payment.objects.get_or_create(
        session=session,
        defaults={
            "merchant": session.merchant,
            "amount": session.amount,
            "fee_amount": session.fee_amount,
            "fee_percentage": session.fee_percentage,
            "fee_source": session.fee_source,
            "pricing_plan": session.pricing_plan,
            "plan_assignment": session.plan_assignment,
            "fee_calculated_at": session.fee_calculated_at,
            "currency": session.currency,
        },
    )
    if created:
        PaymentStatusHistory.objects.create(payment=payment, status=payment.status)
    create_transaction_fee_snapshot(payment)
    return payment


@transaction.atomic
def create_checkout_payment_and_rtp(session, verification):
    """
    Checkout payment workflow:
      1. Lock fee snapshot on session
      2. Create Payment + immutable fee record
      3. Submit RTP via shared gateway rail
    """
    session = ensure_checkout_fee_snapshot(session)
    payment, created = Payment.objects.get_or_create(
        session=session,
        defaults={
            "merchant": session.merchant,
            "payer_alias_type": verification.alias_type,
            "payer_alias": verification.alias_value,
            "payer_display_name": verification.display_name,
            "payer_reference": verification.provider_customer_ref,
            "amount": session.amount,
            "fee_amount": session.fee_amount,
            "fee_percentage": session.fee_percentage,
            "fee_source": session.fee_source,
            "pricing_plan": session.pricing_plan,
            "plan_assignment": session.plan_assignment,
            "fee_calculated_at": session.fee_calculated_at,
            "currency": session.currency,
            "status": Payment.Status.ALIAS_VERIFIED,
        },
    )
    if not created and hasattr(payment, "rtp"):
        return payment.rtp

    create_transaction_fee_snapshot(payment)
    release_code = f"{secrets.randbelow(1_000_000):06d}"
    payment.release_code_hash = make_password(release_code)
    payment.release_code_failed_attempts = 0
    payment.release_code_locked_at = None
    payment.release_code_confirmed_at = None
    payment.save(
        update_fields=[
            "release_code_hash",
            "release_code_failed_attempts",
            "release_code_locked_at",
            "release_code_confirmed_at",
            "updated_at",
        ]
    )

    req_id = new_rtp_request_id()
    payload = {
        "requestId": req_id,
        "paymentReference": payment.reference,
        "payerAlias": verification.alias_value,
        "payerAliasType": verification.alias_type,
        "merchant": {
            "id": session.merchant.merchant_code,
            "name": session.merchant.display_name,
        },
        "order": {
            "number": session.order_number,
            "description": (
                f"{session.description} | AmatoPay release code: {release_code}"
            ),
        },
        "amount": str(session.amount),
        "fee": str(session.fee_amount),
        "totalAmount": str(session.total_amount),
        "currency": session.currency,
    }
    result = call_create_rtp(payload)
    rtp = persist_rtp_request(
        request_id=req_id,
        payload=payload,
        result=result,
        payment=payment,
        release_code=release_code,
    )
    provider_ref = result.get("trxRef") or result.get("providerReference", "")
    payment.provider_reference = provider_ref
    payment.status = Payment.Status.RTP_PENDING
    payment.save(update_fields=["provider_reference", "status", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=payment, status=payment.status, source="rail", payload=result
    )
    session.status = PaymentSession.Status.AWAITING_PAYMENT
    session.save(update_fields=["status", "updated_at"])
    return rtp


@transaction.atomic
def apply_payment_rtp_status(payment, status, data):
    """Apply an RTP status update to a checkout payment and its session."""
    from apps.fiduciary.services import hold_funds

    mapping = {
        "PENDING": Payment.Status.RTP_PENDING,
        "AWAITING_APPROVAL": Payment.Status.AWAITING_APPROVAL,
        "PROCESSING": Payment.Status.PROCESSING,
        "COMPLETED": Payment.Status.PAID,
        "REJECTED": Payment.Status.REJECTED,
        "FAILED": Payment.Status.FAILED,
        "CANCELLED": Payment.Status.CANCELLED,
    }
    payment.status = mapping[status]
    payment.failure_code = data.get("reasonCode", "")
    if status == "COMPLETED":
        payment.paid_at = data.get("completedAt") or timezone.now()
    payment.save(update_fields=["status", "failure_code", "paid_at", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=payment,
        status=payment.status,
        source="rail",
        reason=payment.failure_code,
        payload=data,
    )
    if status == "COMPLETED":
        hold_funds(payment)
        payment.session.status = PaymentSession.Status.COMPLETED
        payment.session.save(update_fields=["status", "updated_at"])
        emit_event(
            payment.merchant,
            "payment.paid",
            {
                "payment_reference": payment.reference,
                "order_number": payment.session.order_number,
                "status": payment.status,
                "amount": str(payment.amount),
                "fee_amount": str(payment.fee_amount),
                "fee_percentage": str(payment.fee_percentage),
                "net_amount": str(payment.net_amount),
                "fee_source": payment.fee_source,
                "total_amount": str(payment.total_amount),
                "currency": payment.currency,
            },
            "payment",
            payment.reference,
        )
    elif status in {"REJECTED", "FAILED", "CANCELLED"}:
        payment.session.status = PaymentSession.Status.FAILED
        payment.session.save(update_fields=["status", "updated_at"])
        emit_event(
            payment.merchant,
            "payment.failed",
            {
                "payment_reference": payment.reference,
                "status": payment.status,
                "reason_code": payment.failure_code,
            },
            "payment",
            payment.reference,
        )
