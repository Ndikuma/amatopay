from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.gateway.services import start_merchant_payout
from apps.fiduciary.models import FundHold
from apps.fiduciary.services import release_hold
from apps.payments.models import Payment
from apps.webhooks.services import emit_event

from .models import (
    Delivery,
    DeliveryConfirmation,
    ProtectionClaim,
    ProtectionClaimEvidence,
    ProtectionClaimEvent,
)

MAX_RELEASE_CODE_ATTEMPTS = 5


def _validate_release_code(payment, secure_code):
    if payment.release_code_locked_at:
        raise PermissionDenied(
            "Secure code verification is locked after too many failed attempts."
        )
    if not payment.release_code_hash:
        raise ValidationError({"detail": "This payment has no secure release code."})
    if check_password(secure_code, payment.release_code_hash):
        return

    payment.release_code_failed_attempts += 1
    fields = ["release_code_failed_attempts", "updated_at"]
    if payment.release_code_failed_attempts >= MAX_RELEASE_CODE_ATTEMPTS:
        payment.release_code_locked_at = timezone.now()
        fields.append("release_code_locked_at")
    payment.save(update_fields=fields)
    raise PermissionDenied("Invalid secure code.")


def _erase_release_code(payment):
    payment.release_code_hash = ""
    payment.save(update_fields=["release_code_hash", "updated_at"])
    if hasattr(payment, "collection"):
        payment.collection.release_code_ciphertext = ""
        payment.collection.save(update_fields=["release_code_ciphertext", "updated_at"])


def confirm_delivery_with_code(payment, secure_code, delivery_data=None):
    delivery_data = delivery_data or {}
    invalid_code = False

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)

        if payment.release_code_confirmed_at:
            return payment.delivery.confirmation, False
        if payment.status != Payment.Status.DELIVERY_PENDING:
            raise ValidationError(
                {
                    "detail": (
                        "Payment must be completed and held before delivery "
                        "confirmation."
                    )
                }
            )
        try:
            _validate_release_code(payment, secure_code)
        except PermissionDenied:
            invalid_code = True
        if not invalid_code:
            has_destination = payment.merchant.settlement_accounts.filter(
                alias_type="MOBILE",
                verification_status="verified",
                is_primary=True,
                is_active=True,
                currency=payment.currency,
            ).exists()
            if not has_destination:
                raise ValidationError(
                    {
                        "detail": (
                            "Merchant must have an active verified primary MOBILE "
                            f"settlement alias for {payment.currency} before delivery "
                            "can be confirmed."
                        )
                    }
                )
            now = timezone.now()
            delivery, _ = Delivery.objects.get_or_create(payment=payment)
            delivery.status = Delivery.Status.DELIVERED
            delivery.delivered_at = delivery.delivered_at or now
            for field in ("merchant_reference", "tracking_number", "evidence"):
                if field in delivery_data:
                    setattr(delivery, field, delivery_data[field])
            delivery.save()
            confirmation, created = DeliveryConfirmation.objects.get_or_create(
                delivery=delivery,
                defaults={
                    "decision": DeliveryConfirmation.Decision.CONFIRMED,
                    "confirmed_by": DeliveryConfirmation.Method.PAYER_SECURE_CODE,
                    "method": DeliveryConfirmation.Method.PAYER_SECURE_CODE,
                    "metadata": {"proof_method": "secure_code"},
                },
            )

            payment.release_code_confirmed_at = now
            _erase_release_code(payment)
            payment.save(
                update_fields=[
                    "release_code_confirmed_at",
                    "release_code_hash",
                    "updated_at",
                ]
            )
            hold = payment.fund_hold
            hold.status = FundHold.Status.DELIVERY_CONFIRMED
            hold.save(update_fields=["status", "updated_at"])
            release_hold(hold)
            settlement = payment.settlement
            transaction.on_commit(lambda: start_merchant_payout(settlement))
            if created:
                emit_event(
                    payment.merchant,
                    "delivery.confirmed",
                    {
                        "payment_reference": payment.reference,
                        "confirmed_by": confirmation.method,
                        "status": payment.status,
                        "amount": str(payment.amount),
                        "currency": payment.currency,
                    },
                    "payment",
                    payment.reference,
                )
            return confirmation, created

    # Raise after the transaction commits so a failed attempt cannot be rolled back.
    if invalid_code:
        raise PermissionDenied("Invalid secure code.")


@transaction.atomic
def confirm_delivery_instant(payment):
    """Auto-confirm delivery for an instant-settlement session and release funds.

    Called from ``apply_payment_collection_status`` when the checkout session was
    created with ``require_delivery_confirmation=False``. Mirrors the release path
    of :func:`confirm_delivery_with_code` but performs no payer verification —
    there is no secure code for these payments.
    """
    payment = Payment.objects.select_for_update().select_related("merchant", "session").get(pk=payment.pk)

    if payment.release_code_confirmed_at:
        return getattr(getattr(payment, "delivery", None), "confirmation", None), False
    if payment.status != Payment.Status.DELIVERY_PENDING:
        raise ValidationError(
            {"detail": "Payment must be collected and held before settlement."}
        )

    has_destination = payment.merchant.settlement_accounts.filter(
        alias_type="MOBILE",
        verification_status="verified",
        is_primary=True,
        is_active=True,
        currency=payment.currency,
    ).exists()
    if not has_destination:
        raise ValidationError(
            {
                "detail": (
                    "Merchant must have an active verified primary MOBILE settlement "
                    f"alias for {payment.currency} before instant settlement."
                )
            }
        )

    now = timezone.now()
    delivery, _ = Delivery.objects.get_or_create(payment=payment)
    delivery.status = Delivery.Status.DELIVERED
    delivery.delivered_at = delivery.delivered_at or now
    delivery.save()
    confirmation, created = DeliveryConfirmation.objects.get_or_create(
        delivery=delivery,
        defaults={
            "decision": DeliveryConfirmation.Decision.CONFIRMED,
            "confirmed_by": DeliveryConfirmation.Method.INSTANT_SETTLEMENT,
            "method": DeliveryConfirmation.Method.INSTANT_SETTLEMENT,
            "metadata": {"proof_method": "instant_settlement"},
        },
    )

    payment.release_code_confirmed_at = now
    _erase_release_code(payment)
    payment.save(
        update_fields=["release_code_confirmed_at", "release_code_hash", "updated_at"]
    )

    hold = payment.fund_hold
    hold.status = FundHold.Status.DELIVERY_CONFIRMED
    hold.save(update_fields=["status", "updated_at"])
    release_hold(hold)
    settlement = payment.settlement
    transaction.on_commit(lambda: start_merchant_payout(settlement))

    if created:
        emit_event(
            payment.merchant,
            "delivery.confirmed",
            {
                "payment_reference": payment.reference,
                "confirmed_by": confirmation.method,
                "status": payment.status,
                "amount": str(payment.amount),
                "currency": payment.currency,
            },
            "payment",
            payment.reference,
        )
    return confirmation, created


def _normalize_alias(value):
    return "".join(str(value).split()).lower()


def open_customer_delivery_claim(
    payment,
    secure_code,
    *,
    reason,
    description,
    evidence_file=None,
):
    return request_delivery_review(
        payment,
        secure_code,
        reason=reason,
        description=description,
        evidence_file=evidence_file,
        delivery_status=Delivery.Status.FAILED,
        decision=DeliveryConfirmation.Decision.DISPUTED,
        action="customer_reported_delivery_problem",
    )


def request_delivery_review(
    payment,
    secure_code,
    *,
    reason,
    description,
    evidence_file=None,
    delivery_status=Delivery.Status.UNDER_REVIEW,
    decision=DeliveryConfirmation.Decision.REVIEW,
    action="customer_requested_manual_delivery_review",
):
    invalid_code = False
    result = None
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == Payment.Status.DISPUTED:
            claim = payment.protection_claims.exclude(
                status=ProtectionClaim.Status.CLOSED
            ).order_by("-created_at").first()
            if claim:
                return claim, False
        if payment.status != Payment.Status.DELIVERY_PENDING:
            raise ValidationError(
                {"detail": "This payment is not eligible for a delivery investigation."}
            )

        try:
            _validate_release_code(payment, secure_code)
        except PermissionDenied:
            invalid_code = True

        authenticated_by = DeliveryConfirmation.Method.PAYER_SECURE_CODE
        if not invalid_code:
            delivery, _ = Delivery.objects.get_or_create(payment=payment)
            delivery.status = delivery_status
            delivery.save(update_fields=["status", "updated_at"])
            DeliveryConfirmation.objects.get_or_create(
                delivery=delivery,
                defaults={
                    "decision": decision,
                    "confirmed_by": authenticated_by,
                    "method": authenticated_by,
                    "notes": description,
                    "metadata": {"proof_method": authenticated_by, "reason": reason},
                },
            )
            claim = ProtectionClaim.objects.create(
                payment=payment,
                reason=reason,
                description=description,
                opened_by=f"payer_public_portal:{authenticated_by}",
            )
            if evidence_file:
                ProtectionClaimEvidence.objects.create(
                    claim=claim,
                    submitted_by=f"payer_public_portal:{authenticated_by}",
                    description="Evidence supplied with the customer delivery request.",
                    file=evidence_file,
                )
            ProtectionClaimEvent.objects.create(
                claim=claim,
                action=action,
                actor=f"payer_public_portal:{authenticated_by}",
                notes=description,
            )
            payment.status = Payment.Status.DISPUTED
            _erase_release_code(payment)
            payment.save(update_fields=["status", "release_code_hash", "updated_at"])
            hold = payment.fund_hold
            hold.status = FundHold.Status.DISPUTED
            hold.freeze_reason = f"Customer delivery review: {reason}"
            hold.save(update_fields=["status", "freeze_reason", "updated_at"])
            emit_event(
                payment.merchant,
                "payment.disputed",
                {
                    "payment_reference": payment.reference,
                    "claim_reference": str(claim.pk),
                    "reason": reason,
                    "description": description,
                    "status": payment.status,
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                },
                "payment",
                payment.reference,
            )
            result = (claim, True)
    if invalid_code:
        raise PermissionDenied("Invalid secure code.")
    return result
