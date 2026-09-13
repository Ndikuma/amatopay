import logging
import secrets

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from apps.billing.services import (
    create_transaction_fee_snapshot,
    ensure_checkout_fee_snapshot,
)
from apps.checkout.models import PaymentSession
from apps.gateway import client
from apps.gateway.collection import (
    PaymentGatewayError,
    call_create_collection,
    new_collection_request_id,
    persist_collection_request,
)
from apps.gateway.models import GatewayConfig, QRPaymentWatch
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
def start_qr_watch(payment):
    """Open a watch on AmatoPay's shared QR for this payment. Idempotent.

    Unlike the alias flow, this never calls ``create_collection`` — there is
    no known payer to push a request to. ``poll_qr_payments`` discovers the
    matching transaction later and hands off to :func:`record_qr_collection`,
    which converges into the *existing*, untouched collection reconciler
    (``reconcile_gateway`` / ``recover_collection_status``) for status
    resolution — the QR endpoints are only ever used here, for discovery.
    """
    if hasattr(payment, "qr_watch"):
        return payment.qr_watch
    config = GatewayConfig.active()
    if not config or not config.qr_code_text:
        raise PaymentGatewayError(
            "QR payments are not configured. Contact AmatoPay."
        )
    try:
        result = client.qr_scan(config.qr_code_text)
    except Exception as exc:
        from apps.gateway.provider import MobileCashGatewayError

        if isinstance(exc, MobileCashGatewayError):
            raise PaymentGatewayError(
                "QR payment could not be started. Please try again."
            ) from exc
        raise

    # AmatoPay's own code must be the one that was actually scanned — refuse
    # to watch a QR the provider says belongs to a different creditor alias,
    # and refuse a code that isn't currently usable.
    scanned_creditor = str(result.get("creditorAlias") or "").strip()
    if scanned_creditor and scanned_creditor != config.creditor_alias.strip():
        raise PaymentGatewayError(
            "QR payments are misconfigured (creditor alias mismatch). Contact AmatoPay."
        )
    qr_status = str(result.get("status") or "").strip().upper()
    if qr_status in {"EXPIRED", "CANCELLED"}:
        raise PaymentGatewayError(
            "AmatoPay's QR code is no longer usable. Contact AmatoPay."
        )
    if result.get("isLocked"):
        raise PaymentGatewayError(
            "AmatoPay's QR code is currently in use. Please try again shortly."
        )

    watch = QRPaymentWatch.objects.create(
        payment=payment,
        qr_header_uuid=result.get("qrHeaderUUID", ""),
        qr_extension_uuids=result.get("qrExtensionUUIDs", []),
        qr_type=result.get("qrType", ""),
        raw_scan_response=result.get("provider", {}),
    )
    payment.status = Payment.Status.QR_PENDING
    payment.save(update_fields=["status", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=payment, status=payment.status, source="qr"
    )
    payment.session.status = PaymentSession.Status.AWAITING_PAYMENT
    payment.session.save(update_fields=["status", "updated_at"])
    return watch


@transaction.atomic
def record_qr_collection(payment, trx_ref):
    """Materialize the ``GatewayRequest`` once ``poll_qr_payments`` discovers a trxRef.

    From this point the payment is handled exactly like an alias-initiated
    collection: ``reconcile_gateway`` (untouched) polls
    ``TRANSACTION_BY_REFERENCE`` for the authoritative status and applies it
    via the existing :func:`apply_payment_collection_status`. The status here
    is deliberately set to PROCESSING regardless of the discovery snapshot —
    the reference poll is the single source of truth, not this sighting.
    """
    if hasattr(payment, "collection"):
        return payment.collection

    session = payment.session
    protected = session.require_delivery_confirmation
    release_code = f"{secrets.randbelow(1_000_000):06d}" if protected else None
    payment.release_code_hash = make_password(release_code) if protected else ""
    payment.release_code_failed_attempts = 0
    payment.release_code_locked_at = None
    payment.release_code_confirmed_at = None
    payment.provider_reference = trx_ref
    payment.status = Payment.Status.COLLECTION_PENDING
    payment.save(
        update_fields=[
            "release_code_hash",
            "release_code_failed_attempts",
            "release_code_locked_at",
            "release_code_confirmed_at",
            "provider_reference",
            "status",
            "updated_at",
        ]
    )
    req_id = new_collection_request_id(prefix="AMP-QR")
    collection = persist_collection_request(
        request_id=req_id,
        payload={"paymentReference": payment.reference, "trxRef": trx_ref, "source": "qr"},
        result={"trxRef": trx_ref, "status": "PROCESSING"},
        payment=payment,
        release_code=release_code,
    )
    PaymentStatusHistory.objects.create(
        payment=payment, status=payment.status, source="qr"
    )
    session.status = PaymentSession.Status.AWAITING_PAYMENT
    session.save(update_fields=["status", "updated_at"])
    return collection


@transaction.atomic
def create_checkout_payment(session, verification):
    """Create the Payment record + immutable fee snapshot for a verified session.

    Does NOT contact the payment gateway. The collection is submitted later
    by :func:`submit_checkout_payment_collection` (via the ``process_pending_payments``
    management command), so merchant checkout creation never blocks on the rail.
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
    if created:
        create_transaction_fee_snapshot(payment)
        PaymentStatusHistory.objects.create(
            payment=payment, status=payment.status, source="checkout"
        )
    return payment


@transaction.atomic
def submit_checkout_payment_collection(payment):
    """Submit the collection for a checkout payment. Idempotent.

    Called out-of-band (management command / retry) so the payer-facing
    request that created the payment never waits for the gateway.
    """
    payment = (
        Payment.objects.select_for_update()
        .select_related("session", "merchant")
        .get(pk=payment.pk)
    )
    if hasattr(payment, "collection"):
        return payment.collection
    if payment.status not in {
        Payment.Status.ALIAS_VERIFIED,
        Payment.Status.CREATED,
    }:
        return getattr(payment, "collection", None)

    session = payment.session
    # Instant-settlement sessions have no delivery gate, so no secure code.
    protected = session.require_delivery_confirmation
    release_code = f"{secrets.randbelow(1_000_000):06d}" if protected else None
    payment.release_code_hash = make_password(release_code) if protected else ""
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

    description = (
        f"{session.description} | AmatoPay release code: {release_code}"
        if protected
        else session.description
    )
    req_id = new_collection_request_id()
    payload = {
        "requestId": req_id,
        "paymentReference": payment.reference,
        "payerAlias": payment.payer_alias,
        "payerAliasType": payment.payer_alias_type,
        "merchant": {
            "id": payment.merchant.merchant_code,
            "name": payment.merchant.display_name,
        },
        "order": {
            "number": session.order_number,
            "description": description,
        },
        "amount": str(payment.amount),
        "fee": str(payment.fee_amount),
        "totalAmount": str(payment.total_amount),
        "currency": payment.currency,
    }
    result = call_create_collection(payload)
    collection = persist_collection_request(
        request_id=req_id,
        payload=payload,
        result=result,
        payment=payment,
        release_code=release_code,
    )
    provider_ref = result.get("trxRef") or result.get("providerReference", "")
    payment.provider_reference = provider_ref
    payment.status = Payment.Status.COLLECTION_PENDING
    payment.save(update_fields=["provider_reference", "status", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=payment, status=payment.status, source="rail", payload=result
    )
    session.status = PaymentSession.Status.AWAITING_PAYMENT
    session.save(update_fields=["status", "updated_at"])
    return collection


@transaction.atomic
def create_checkout_payment_and_collection(session, verification):
    """Synchronous variant: create the payment and immediately submit the collection."""
    payment = create_checkout_payment(session, verification)
    return submit_checkout_payment_collection(payment)


def _resolve_qr_payer_identity(payment, debtor_alias):
    """Best-effort: QR payments have no known payer until the gateway's
    transaction lookup reveals one (``debtorAlias``). Verify it the same way
    the alias-push flow verifies its payer upfront, so a completed QR
    payment ends up just as complete a record. Never blocks completion — a
    missing/failed lookup just leaves payer fields blank, exactly as today.

    Returns the list of Payment field names it set, if any, so the caller
    can include them in its own ``save(update_fields=...)``.
    """
    debtor_alias = (debtor_alias or "").strip()
    if not debtor_alias:
        return []

    from apps.gateway.services import AliasNotPayableError, verify_merchant_payer_alias

    try:
        verification = verify_merchant_payer_alias(
            merchant=payment.merchant, payer_alias=debtor_alias
        )
    except AliasNotPayableError:
        return []
    except Exception:
        logging.getLogger(__name__).exception(
            "Could not verify QR payer alias for payment %s", payment.reference
        )
        return []

    verification.session = payment.session
    verification.save(update_fields=["session", "updated_at"])
    payment.payer_alias_type = "MOBILE"
    payment.payer_alias = verification.alias_value
    payment.payer_display_name = verification.display_name
    payment.payer_reference = verification.provider_customer_ref
    return ["payer_alias_type", "payer_alias", "payer_display_name", "payer_reference"]


@transaction.atomic
def apply_payment_collection_status(payment, status, data):
    """Apply an collection status update to a checkout payment and its session."""
    from apps.fiduciary.services import hold_funds

    mapping = {
        "PENDING": Payment.Status.COLLECTION_PENDING,
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
    update_fields = ["status", "failure_code", "paid_at", "updated_at"]
    if status == "COMPLETED" and not payment.payer_alias:
        update_fields += _resolve_qr_payer_identity(payment, data.get("debtorAlias"))
    payment.save(update_fields=update_fields)
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
                "instant_settlement": not payment.session.require_delivery_confirmation,
            },
            "payment",
            payment.reference,
        )
        # Instant-settlement sessions have no delivery gate: auto-confirm and
        # release straight away. Runs after payment.paid so that event still
        # carries the clean "held" status.
        if not payment.session.require_delivery_confirmation:
            from apps.deliveries.services import confirm_delivery_instant

            confirm_delivery_instant(payment)
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
