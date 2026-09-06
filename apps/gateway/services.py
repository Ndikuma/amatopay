import time
import re
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from apps.fiduciary.models import FiduciaryEntry
from apps.settlements.models import Settlement
from .models import (
    AliasVerification,
    GatewayCallback,
    GatewayRequest,
    GatewayTransactionPoll,
)
from . import client
from .collection import PaymentGatewayError, redact_release_code
from apps.webhooks.services import emit_event

# Re-export for callers that import from gateway.services
__all__ = [
    "AliasNotPayableError",
    "PaymentGatewayError",
    "verify_merchant_payer_alias",
    "persist_alias_result",
    "create_checkout_and_collection",
    "create_payment_and_collection",
    "apply_collection_status",
    "recover_collection_status",
    "start_merchant_payout",
    "recover_p2p_status",
    "apply_p2p_status",
]


class AliasNotPayableError(ValueError):
    pass


def verify_merchant_payer_alias(*, merchant, payer_alias):
    """Verify and record a MOBILE payer alias for a merchant checkout."""
    import uuid
    from .provider import MobileCashGatewayError

    request_id = f"AMP-ALIAS-{uuid.uuid4().hex[:16].upper()}"
    try:
        result = client.verify_alias(
            {"requestId": request_id, "alias": payer_alias, "aliasType": "MOBILE"}
        )
    except MobileCashGatewayError as exc:
        raise PaymentGatewayError(
            "Alias verification is temporarily unavailable. Please try again."
        ) from exc
    found = bool(result.get("found", result.get("valid", False)))
    if not found:
        raise AliasNotPayableError("This mobile alias could not be found.")
    if str(result.get("status", "")).upper() != "ACTIVE":
        raise AliasNotPayableError("This mobile alias is not active for payments.")
    result.setdefault("requestId", request_id)
    verification = persist_alias_result(None, "MOBILE", payer_alias, result)
    verification.merchant = merchant
    verification.save(update_fields=["merchant", "updated_at"])
    return verification


def create_checkout_and_collection(*, merchant, payer_alias, session_data):
    """Backward-compatible wrapper — delegates to checkout workflow."""
    from apps.checkout.services import create_checkout_session

    return create_checkout_session(
        merchant=merchant,
        payer_alias=payer_alias,
        session_data=session_data,
    )


def create_payment_and_collection(session, av):
    """Backward-compatible wrapper — delegates to payments checkout workflow."""
    from apps.payments.services import create_checkout_payment_and_collection

    return create_checkout_payment_and_collection(session, av)


@transaction.atomic
def persist_alias_result(session, alias_type, alias_value, result):
    import uuid
    from apps.checkout.models import PaymentSession

    request_id = (
        result.get("request_id")
        or result.get("requestId")
        or f"AMP-ALIAS-{uuid.uuid4().hex[:16].upper()}"
    )
    customer_data = result.get("customer") or {}
    account_data = result.get("account") or {}
    found = bool(result.get("found", result.get("valid", False)))
    av = AliasVerification.objects.create(
        request_id=request_id,
        session=session,
        alias_type=alias_type,
        alias_value=alias_value,
        found=found,
        status=result.get("status", ""),
        display_name=customer_data.get("name", customer_data.get("display_name", "")),
        provider_customer_ref=customer_data.get("reference", ""),
        account_type=account_data.get("type", account_data.get("account_type", "")),
        currency=account_data.get("currency", "BIF"),
        raw_response=result,
    )
    if session is not None and found and av.status.upper() == "ACTIVE":
        session.payer_display_name = av.display_name
        session.status = PaymentSession.Status.ALIAS_VERIFIED
        session.save(update_fields=["payer_display_name", "status", "updated_at"])
    return av


@transaction.atomic
def apply_collection_status(data):
    """
    Apply an collection status update from callback or polling.
    Dispatches to billing or checkout (payments) workflow handlers.
    """
    existing = GatewayCallback.objects.filter(event_id=data["eventId"]).first()
    if existing:
        return existing
    trx_ref = data.get("trxRef") or data.get("providerReference")
    if not trx_ref:
        raise ValueError("collection status update is missing trxRef")

    collection_qs = (
        GatewayRequest.objects.select_for_update()
        .filter(rail=GatewayRequest.Rail.COLLECTION)
        .select_related("payment", "plan_request")
    )
    payment_ref = data.get("paymentReference", "")
    collection = (
        collection_qs.filter(payment__reference=payment_ref, provider_reference=trx_ref).first()
        or collection_qs.filter(
            plan_request__reference=payment_ref, provider_reference=trx_ref
        ).first()
    )
    if not collection:
        raise GatewayRequest.DoesNotExist(
            f"No collection GatewayRequest found for paymentReference={payment_ref} trxRef={trx_ref}"
        )

    callback = GatewayCallback.objects.create(
        event_id=data["eventId"],
        request=collection,
        status=data["status"],
        reason_code=data.get("reasonCode", ""),
        payload=data,
    )
    collection.status = data["status"].lower()
    collection.last_callback_at = timezone.now()
    collection.save(update_fields=["status", "last_callback_at", "updated_at"])

    status = data["status"]
    if collection.plan_request_id:
        from apps.billing.services import apply_billing_collection_status

        apply_billing_collection_status(collection, status, data)
    else:
        from apps.payments.services import apply_payment_collection_status

        apply_payment_collection_status(collection.payment, status, data)

    return callback


def recover_collection_status(collection):
    import logging

    """Poll MobileCash and apply the collection result idempotently."""
    result = _poll_transaction(collection, GatewayTransactionPoll.Rail.COLLECTION, client.get_collection_status)
    status = str(result.get("status", "PENDING")).upper()
    if status == collection.status.upper():
        return None
    if collection.plan_request_id:
        payment_ref = collection.plan_request.reference
    elif collection.payment_id:
        payment_ref = collection.payment.reference
    else:
        logging.getLogger(__name__).warning(
            "Skipping collection poll for %s: no associated payment or billing object.",
            collection.request_id,
        )
        return None
    return apply_collection_status(
        {
            "eventId": f"poll-{collection.provider_reference}-{status.lower()}",
            "paymentReference": payment_ref,
            "trxRef": collection.trx_ref,
            "status": status,
            "reasonCode": result.get("reasonCode", ""),
        }
    )


@transaction.atomic
def start_merchant_payout(settlement):
    import uuid
    from apps.payments.models import Payment, PaymentStatusHistory

    settlement = (
        Settlement.objects.select_for_update()
        .select_related("merchant", "payment")
        .get(pk=settlement.pk)
    )
    existing_payout = GatewayRequest.objects.filter(
        rail=GatewayRequest.Rail.P2P, settlement=settlement
    ).first()
    if existing_payout:
        return existing_payout
    if settlement.status not in {Settlement.Status.PENDING, Settlement.Status.FAILED}:
        raise ValueError("Settlement is not eligible for payout")
    if settlement.payment.fund_hold.status != "release_pending":
        raise ValueError("Funds must be release-pending before merchant payout")
    destination = settlement.merchant.settlement_accounts.filter(
        alias_type="MOBILE",
        verification_status="verified",
        is_primary=True,
        is_active=True,
        currency=settlement.payment.currency,
    ).first()
    if not destination:
        raise ValueError(
            "Merchant has no active verified primary MOBILE settlement account "
            f"for {settlement.payment.currency}"
        )
    req_id = f"AMP-P2P-{uuid.uuid4().hex[:16].upper()}"
    payload = {
        "requestId": req_id,
        "settlementReference": settlement.reference,
        "paymentReference": settlement.payment.reference,
        "beneficiary": {
            "aliasType": destination.alias_type,
            "alias": destination.alias_value,
            "name": destination.account_name or settlement.merchant.display_name,
        },
        "amount": str(settlement.net_amount),
        "currency": settlement.payment.currency,
        "description": f"AmatoPay merchant settlement {settlement.reference}",
        "merchantReference": settlement.merchant.merchant_code,
    }
    try:
        result = client.create_p2p(payload)
    except Exception as exc:
        from .provider import MobileCashGatewayError
        if isinstance(exc, MobileCashGatewayError):
            raise PaymentGatewayError(
                "Payout could not be initiated. Please try again."
            ) from exc
        raise
    provider_ref = result.get("trxRef") or result.get("providerReference", "")
    if not provider_ref:
        raise PaymentGatewayError("Payout could not be initiated. Please try again.")
    p2p = GatewayRequest.objects.create(
        rail=GatewayRequest.Rail.P2P,
        request_id=req_id,
        settlement=settlement,
        provider_reference=provider_ref,
        status=result.get("status", "PROCESSING").lower(),
        raw_request=payload,
        raw_response=result,
    )
    settlement.status = Settlement.Status.PROCESSING
    settlement.provider_reference = provider_ref
    settlement.beneficiary_alias = destination.alias_value
    settlement.save(
        update_fields=[
            "status",
            "provider_reference",
            "beneficiary_alias",
            "updated_at",
        ]
    )
    payment = settlement.payment
    payment.status = Payment.Status.SETTLEMENT_PROCESSING
    payment.save(update_fields=["status", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=payment, status=payment.status, source="settlement"
    )
    if str(result.get("status", "")).upper() == "COMPLETED":
        apply_p2p_status(
            {
                "eventId": f"sync-{provider_ref}-completed",
                "settlementReference": settlement.reference,
                "paymentReference": payment.reference,
                "trxRef": provider_ref,
                "status": "COMPLETED",
            }
        )
    return p2p


def recover_p2p_status(p2p):
    """Poll a MobileCash P2P payout when no institution callback is available."""
    result = _poll_transaction(p2p, GatewayTransactionPoll.Rail.P2P, client.get_p2p_status)
    status = str(result.get("status", "PROCESSING")).upper()
    if status == p2p.status.upper():
        return None
    return apply_p2p_status(
        {
            "eventId": f"poll-{p2p.provider_reference}-{status.lower()}",
            "settlementReference": p2p.settlement.reference,
            "paymentReference": p2p.settlement.payment.reference,
            "trxRef": p2p.trx_ref,
            "status": status,
            "reasonCode": result.get("reasonCode", ""),
        }
    )


def _poll_transaction(request_record, rail, getter):
    """Poll by the persisted trxRef and retain durable retry/audit state."""
    started = time.monotonic()
    now = timezone.now()
    try:
        result = getter(request_record.trx_ref)
    except Exception as exc:
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        status_code = getattr(exc, "status_code", None)
        failures = request_record.consecutive_poll_failures + 1
        base_delay = 30 if status_code == 429 else 10
        delay = min(base_delay * (2 ** (failures - 1)), 300)
        type(request_record).objects.filter(pk=request_record.pk).update(
            last_polled_at=now,
            next_poll_at=now + timedelta(seconds=delay),
            poll_attempts=models.F("poll_attempts") + 1,
            consecutive_poll_failures=failures,
            last_poll_error=str(exc)[:2000],
        )
        GatewayTransactionPoll.objects.create(
            rail=rail,
            request_id=request_record.request_id,
            trx_ref=request_record.trx_ref,
            succeeded=False,
            error=str(exc)[:4000],
            duration_ms=duration_ms,
        )
        raise
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    new_status = str(result.get("status", "")).upper()
    type(request_record).objects.filter(pk=request_record.pk).update(
        last_polled_at=now,
        next_poll_at=now + timedelta(seconds=20),
        poll_attempts=models.F("poll_attempts") + 1,
        consecutive_poll_failures=0,
        last_poll_error="",
    )
    current_status = request_record.status.upper()
    if new_status and new_status != current_status:
        GatewayTransactionPoll.objects.create(
            rail=rail,
            request_id=request_record.request_id,
            trx_ref=request_record.trx_ref,
            status=new_status,
            succeeded=True,
            response=result,
            duration_ms=duration_ms,
        )
    return result


@transaction.atomic
def apply_p2p_status(data):
    from apps.payments.models import Payment, PaymentStatusHistory

    existing = GatewayCallback.objects.filter(event_id=data["eventId"]).first()
    if existing:
        return existing
    trx_ref = data.get("trxRef") or data.get("providerReference")
    if not trx_ref:
        raise ValueError("P2P status update is missing trxRef")
    settlement = (
        Settlement.objects.select_for_update()
        .select_related("payment")
        .get(reference=data["settlementReference"])
    )
    p2p = GatewayRequest.objects.select_for_update().get(
        rail=GatewayRequest.Rail.P2P,
        settlement=settlement,
        provider_reference=trx_ref,
    )
    callback = GatewayCallback.objects.create(
        event_id=data["eventId"],
        request=p2p,
        status=data["status"],
        reason_code=data.get("reasonCode", ""),
        payload=data,
    )
    p2p.status = data["status"].lower()
    p2p.last_callback_at = timezone.now()
    p2p.save(update_fields=["status", "last_callback_at", "updated_at"])
    if data["status"] == "COMPLETED":
        settlement.status = Settlement.Status.COMPLETED
        settlement.completed_at = data.get("completedAt") or timezone.now()
        settlement.save(update_fields=["status", "completed_at", "updated_at"])
        hold = settlement.payment.fund_hold
        hold.status = "released"
        hold.released_at = settlement.completed_at
        hold.save(update_fields=["status", "released_at", "updated_at"])
        payment = settlement.payment
        ledger_defaults = {
            "account": hold.fiduciary_account,
            "payment": payment,
            "direction": FiduciaryEntry.Direction.DEBIT,
        }
        FiduciaryEntry.objects.get_or_create(
            payment=payment,
            kind=FiduciaryEntry.Kind.RELEASE,
            reference=settlement.reference,
            defaults={
                **ledger_defaults,
                "amount": settlement.net_amount,
                "narrative": "Net merchant settlement released",
            },
        )
        if payment.fee_amount:
            FiduciaryEntry.objects.get_or_create(
                payment=payment,
                kind=FiduciaryEntry.Kind.FEE,
                reference=settlement.reference,
                defaults={
                    **ledger_defaults,
                    "amount": payment.fee_amount,
                    "narrative": "AmatoPay transaction fee allocated",
                },
            )
        payment.status = Payment.Status.SETTLED
        payment.save(update_fields=["status", "updated_at"])
        PaymentStatusHistory.objects.create(
            payment=payment, status=payment.status, source="settlement", payload=data
        )
        emit_event(
            payment.merchant,
            "settlement.completed",
            {
                "payment_reference": payment.reference,
                "settlement_reference": settlement.reference,
                "amount": str(settlement.net_amount),
                "currency": payment.currency,
            },
            "settlement",
            settlement.reference,
        )
    elif data["status"] in {"FAILED", "REJECTED", "CANCELLED"}:
        settlement.status = Settlement.Status.FAILED
        settlement.failure_code = data.get("reasonCode", "")
        settlement.save(update_fields=["status", "failure_code", "updated_at"])
        emit_event(
            settlement.merchant,
            "settlement.failed",
            {
                "payment_reference": settlement.payment.reference,
                "settlement_reference": settlement.reference,
                "reason_code": settlement.failure_code,
            },
            "settlement",
            settlement.reference,
        )
    return callback
