"""Checkout workflow: session creation, alias verification, and payment collection."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.gateway.models import AliasVerification
from apps.gateway.services import AliasNotPayableError, verify_merchant_payer_alias
from apps.payments.services import create_checkout_payment, initiate_payment, start_qr_watch

from .models import PaymentSession


@transaction.atomic
def create_checkout_session(*, merchant, payer_alias, session_data):
    """
    Checkout workflow:
      1. Verify payer alias via gateway (fast lookup — input validation)
      2. Create a three-hour payment session + Payment record
      3. Return immediately. The collection is submitted out-of-band by the
         ``process_pending_payments`` command so this call never blocks on the rail.
    """
    verification = verify_merchant_payer_alias(
        merchant=merchant,
        payer_alias=payer_alias,
    )
    verification = AliasVerification.objects.select_for_update().filter(
        pk=verification.pk,
        merchant=merchant,
        session__isnull=True,
        found=True,
        status__iexact="ACTIVE",
        created_at__gte=timezone.now() - timedelta(minutes=15),
    ).first()
    if not verification:
        raise AliasNotPayableError("The payer alias verification is no longer valid.")

    session = PaymentSession.objects.create(
        merchant=merchant,
        payer_alias=verification.alias_value,
        payer_display_name=verification.display_name,
        expires_at=timezone.now() + timedelta(hours=3),
        status=PaymentSession.Status.ALIAS_VERIFIED,
        **session_data,
    )
    verification.session = session
    verification.save(update_fields=["session", "updated_at"])
    create_checkout_payment(session, verification)
    return PaymentSession.objects.get(pk=session.pk)


@transaction.atomic
def create_qr_checkout_session(*, merchant, session_data, payer_alias):
    """
    QR checkout workflow — the payer alias is required and verified upfront,
    exactly like the push flow. What differs is the collection mechanism,
    not payer identity: AmatoPay never pushes a request to this alias.
      1. Verify payer alias via gateway (fast lookup — input validation),
         same as the push flow.
      2. Create a three-hour payment session + Payment record, payer fields
         already populated.
      3. Open a watch on AmatoPay's shared QR (``start_qr_watch``); the payer
         scans it and pays through their own banking app.
      4. Return immediately. ``poll_qr_payments`` discovers the matching
         transaction out-of-band.
    """
    verification = verify_merchant_payer_alias(merchant=merchant, payer_alias=payer_alias)

    session = PaymentSession.objects.create(
        merchant=merchant,
        payment_method=PaymentSession.PaymentMethod.QR,
        payer_alias=verification.alias_value,
        payer_display_name=verification.display_name,
        expires_at=timezone.now() + timedelta(hours=3),
        status=PaymentSession.Status.CREATED,
        **session_data,
    )
    verification.session = session
    verification.save(update_fields=["session", "updated_at"])

    payment = initiate_payment(session)
    payment.payer_alias_type = "MOBILE"
    payment.payer_alias = verification.alias_value
    payment.payer_display_name = verification.display_name
    payment.payer_reference = verification.provider_customer_ref
    payment.save(
        update_fields=[
            "payer_alias_type",
            "payer_alias",
            "payer_display_name",
            "payer_reference",
            "updated_at",
        ]
    )
    start_qr_watch(payment)
    return PaymentSession.objects.get(pk=session.pk)
