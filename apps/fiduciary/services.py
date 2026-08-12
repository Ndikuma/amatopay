from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .models import FiduciaryAccount, FundHold, FiduciaryEntry
from apps.payments.models import Payment, PaymentStatusHistory


def add_business_days(start, days):
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


@transaction.atomic
def hold_funds(payment, international=False):
    account = FiduciaryAccount.objects.filter(
        currency=payment.currency, active=True, verified_at__isnull=False
    ).first()
    if not account:
        raise ValueError(
            "No verified AmatoPay fiduciary account configured for this currency. "
            "Run sync_fiduciary_account after activating the gateway."
        )
    now = timezone.now()
    eligible = (
        now + timedelta(days=settings.INTERNATIONAL_HOLD_CALENDAR_DAYS)
        if international
        else add_business_days(now, settings.DOMESTIC_HOLD_BUSINESS_DAYS)
    )
    hold, created = FundHold.objects.get_or_create(
        payment=payment,
        defaults={
            "fiduciary_account": account,
            "amount": payment.total_amount,
            "release_eligible_at": eligible,
            "international": international,
            "status": FundHold.Status.DELIVERY_PENDING,
        },
    )
    if created:
        FiduciaryEntry.objects.create(
            account=account,
            payment=payment,
            direction=FiduciaryEntry.Direction.CREDIT,
            kind=FiduciaryEntry.Kind.CUSTOMER_FUNDS,
            amount=payment.total_amount,
            reference=payment.reference,
            narrative="E-commerce payment received into fiduciary funds",
        )
    payment.status = Payment.Status.DELIVERY_PENDING
    payment.save(update_fields=["status", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=payment, status=payment.status, source="fiduciary"
    )
    return hold


@transaction.atomic
def mark_release_pending(hold):
    if hold.status in {FundHold.Status.DISPUTED, FundHold.Status.FROZEN}:
        raise ValueError("Disputed/frozen funds cannot be released")
    hold.status = FundHold.Status.RELEASE_PENDING
    hold.save(update_fields=["status", "updated_at"])
    hold.payment.status = Payment.Status.RELEASE_PENDING
    hold.payment.save(update_fields=["status", "updated_at"])
    PaymentStatusHistory.objects.create(
        payment=hold.payment, status=hold.payment.status, source="fiduciary"
    )
    return hold


@transaction.atomic
def create_settlement_from_hold(hold):
    from apps.settlements.models import Settlement

    if hold.status != FundHold.Status.RELEASE_PENDING:
        raise ValueError("Hold is not release-pending")
    p = hold.payment
    net_amount = p.net_amount
    if net_amount <= 0:
        raise ValueError("Pricing fees cannot consume the full merchant amount")
    return Settlement.objects.get_or_create(
        payment=p,
        defaults={
            "merchant": p.merchant,
            "gross_amount": p.amount,
            "gateway_fee": 0,
            "merchant_fee": p.fee_amount,
            "refund_amount": 0,
            "net_amount": net_amount,
        },
    )[0]


@transaction.atomic
def release_hold(hold):
    """Approve the hold for payout and create a settlement. Actual release occurs only after P2P completes."""
    if hold.status not in {
        FundHold.Status.DELIVERY_CONFIRMED,
        FundHold.Status.RELEASE_PENDING,
    }:
        raise ValueError(
            "Hold must be delivery-confirmed/release-pending before payout"
        )
    if hold.status != FundHold.Status.RELEASE_PENDING:
        mark_release_pending(hold)
    create_settlement_from_hold(hold)
    return hold
