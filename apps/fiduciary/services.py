from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    FiduciaryAccount,
    FiduciaryQRCode,
    FiduciaryQRExtension,
    FundHold,
    FiduciaryEntry,
)
from apps.gateway import client
from apps.gateway.collection import PaymentGatewayError
from apps.gateway.models import GatewayConfig
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


def _dt(value):
    """Best-effort ISO-8601 -> aware datetime; None on anything unparseable."""
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def _money(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


@transaction.atomic
def sync_fiduciary_qr_code():
    """Scan AmatoPay's own registered QR and persist the full response.

    Calls the same ``qr.scan()`` gateway operation ``start_qr_watch`` uses
    for a payment, but purely to snapshot AmatoPay's QR registration —
    its lock state, TTL, creditor/remittance detail, and every extension —
    onto the single :class:`FiduciaryQRCode` record so ops can see and track
    it directly, not just the two UUIDs a payment watch needs.
    """
    config = GatewayConfig.active()
    if not config:
        raise PaymentGatewayError("No active gateway configuration exists.")
    if not config.qr_code_text.strip():
        raise PaymentGatewayError("The active gateway has no qr_code_text configured.")

    scan_result = client.qr_scan(config.qr_code_text.strip(), wait_seconds=120)
    data = scan_result.get("provider") or {}

    ttl = data.get("ttl") or {}
    qr_code, _created = FiduciaryQRCode.objects.select_for_update().get_or_create(
        singleton_key="AMATOPAY"
    )
    qr_code.provider_row_id = str(data.get("rowid") or "")
    qr_code.qr_header_uuid = str(data.get("qrHeaderUUID") or "")
    qr_code.qr_extension_uuid = str(data.get("qrExtensionUUID") or "")
    qr_code.qr_type = str(data.get("qrType") or "")
    qr_code.amount_type = str(data.get("amountType") or "")
    qr_code.currency = str(data.get("currency") or "")[:3]
    qr_code.pmt_context = str(data.get("pmtContext") or "")
    qr_code.iso_ver = data.get("isoVer")
    qr_code.qr_as_text = str(data.get("qrAsText") or "")
    qr_code.qr_as_image = str(data.get("qrAsImage") or "")
    qr_code.status = str(data.get("status") or "")
    qr_code.provider_created_at = _dt(data.get("createdAt"))
    qr_code.expires_at = _dt(data.get("expiresAt"))
    qr_code.last_synced_at = _dt(data.get("lastSyncedAt")) or timezone.now()
    qr_code.creditor_alias = str(data.get("creditorAlias") or "")
    qr_code.merchant_code = str(data.get("merchantCode") or "")
    qr_code.sync_message = str(data.get("syncMessage") or "")
    qr_code.is_locked = bool(data.get("isLocked"))
    qr_code.lock_ttl = data.get("lockTtl")
    qr_code.locked_at = _dt(data.get("lockedAt"))
    qr_code.locked_by = str(data.get("lockedBy") or "")
    qr_code.lock_expires_at = _dt(data.get("lockExpiresAt"))
    qr_code.lock_release_required = bool(data.get("lockReleaseRequired"))
    qr_code.ttl_length = ttl.get("length")
    qr_code.ttl_units = str(ttl.get("units") or "")
    qr_code.creditor_name = str(data.get("creditorName") or "")
    qr_code.creditor_account = str(data.get("creditorAccount") or "")
    qr_code.creditor_agent_bic = str(data.get("creditorAgentBic") or "")
    qr_code.creditor_agent_code_type = str(data.get("creditorAgentCodeType") or "")
    qr_code.is_our_institution = bool(data.get("isOurInstitution"))
    qr_code.amount = _money(data.get("amount"))
    qr_code.amount_min = _money(data.get("amountMin"))
    qr_code.amount_max = _money(data.get("amountMax"))
    qr_code.dba = str(data.get("dba") or "")
    qr_code.end_to_end = str(data.get("endToEnd") or "")
    qr_code.mcc = str(data.get("mcc") or "")
    qr_code.bank_op_code = str(data.get("bankOpCode") or "")
    qr_code.ttc = str(data.get("ttc") or "")
    qr_code.creditor_ref = str(data.get("creditorRef") or "")
    qr_code.customer_type = str(data.get("customerType") or "")
    qr_code.tax_id = str(data.get("taxId") or "")
    qr_code.country_of_residence = str(data.get("countryOfResidence") or "")[:5]
    qr_code.redirect_url = str(data.get("redirectUrl") or "")[:500]
    qr_code.remittance_info = str(data.get("remittanceInfo") or "")
    qr_code.raw_response = data
    qr_code.save()

    synced_uuids = set()
    for extension in data.get("extensions") or []:
        ext_uuid = str(extension.get("qrExtensionUUID") or "")
        if not ext_uuid:
            continue
        synced_uuids.add(ext_uuid)
        row, _ = FiduciaryQRExtension.objects.update_or_create(
            qr_code=qr_code,
            qr_extension_uuid=ext_uuid,
            defaults={
                "provider_row_id": str(extension.get("rowid") or ""),
                "is_last": bool(extension.get("isLast")),
                "status": str(extension.get("status") or ""),
                "creditor_name": str(extension.get("creditorName") or ""),
                "creditor_account": str(extension.get("creditorAccount") or ""),
                "creditor_agent_bic": str(extension.get("creditorAgentBic") or ""),
                "creditor_agent_code_type": str(extension.get("creditorAgentCodeType") or ""),
                "amount": _money(extension.get("amount")),
                "amount_min": _money(extension.get("amountMin")),
                "amount_max": _money(extension.get("amountMax")),
                "dba": str(extension.get("dba") or ""),
                "end_to_end": str(extension.get("endToEnd") or ""),
                "mcc": str(extension.get("mcc") or ""),
                "bank_op_code": str(extension.get("bankOpCode") or ""),
                "ttc": str(extension.get("ttc") or ""),
                "remittance_info": str(extension.get("remittanceInfo") or ""),
                "creditor_ref": str(extension.get("creditorRef") or ""),
                "ttl_length": extension.get("ttlLength"),
                "ttl_units": str(extension.get("ttlUnits") or ""),
                "provider_created_at": _dt(extension.get("createdAt")),
                "last_synced_at": _dt(extension.get("lastSyncedAt")) or timezone.now(),
            },
        )
    # Extensions rotate/expire on the gateway's own TTL — drop ones no longer returned.
    qr_code.extensions.exclude(qr_extension_uuid__in=synced_uuids).delete()

    return qr_code
