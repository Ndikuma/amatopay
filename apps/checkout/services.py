"""Checkout workflow: session creation, alias verification, and payment collection."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.gateway.models import AliasVerification
from apps.gateway.services import AliasNotPayableError, verify_merchant_payer_alias
from apps.payments.services import create_checkout_payment_and_rtp

from .models import PaymentSession


@transaction.atomic
def create_checkout_session(*, merchant, payer_alias, session_data):
    """
    Checkout workflow:
      1. Verify payer alias via gateway
      2. Create a three-hour payment session
      3. Create payment record and initiate RTP collection
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
        status=PaymentSession.Status.CREATED,
        **session_data,
    )
    verification.session = session
    verification.save(update_fields=["session", "updated_at"])
    create_checkout_payment_and_rtp(session, verification)
    return PaymentSession.objects.get(pk=session.pk)
