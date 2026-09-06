from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.deliveries.models import ProtectionClaim
from apps.fiduciary.models import FundHold
from apps.gateway.models import GatewayConfig, GatewayRequest
from apps.merchants.models import Merchant, MerchantKYB
from apps.payments.models import Payment
from apps.settlements.models import Settlement
from apps.webhooks.models import WebhookDelivery


ZERO = Decimal("0.00")


def _money(value):
    return f"{value or ZERO:,.0f} BIF"


def _admin_url(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return "#"


def _short_money(value):
    value = value or ZERO
    if value >= 1_000_000_000:
        return f"{value / Decimal('1000000000'):.1f}B"
    if value >= 1_000_000:
        return f"{value / Decimal('1000000'):.1f}M"
    if value >= 1_000:
        return f"{value / Decimal('1000'):.0f}K"
    return f"{value:.0f}"


def dashboard_callback(request, context):
    now = timezone.now()
    today = timezone.localdate()
    start_of_day = timezone.make_aware(datetime.combine(today, time.min))
    month_start = start_of_day - timedelta(days=29)

    successful = Payment.objects.filter(
        status__in=[
            Payment.Status.PAID,
            Payment.Status.FUNDS_HELD,
            Payment.Status.DELIVERY_PENDING,
            Payment.Status.RELEASE_PENDING,
            Payment.Status.SETTLEMENT_PROCESSING,
            Payment.Status.SETTLED,
        ]
    )
    today_totals = successful.filter(created_at__gte=start_of_day).aggregate(
        count=Count("id"), gross=Sum("amount"), fees=Sum("fee_amount")
    )
    period_totals = successful.filter(created_at__gte=month_start).aggregate(
        count=Count("id"), gross=Sum("amount"), fees=Sum("fee_amount")
    )
    active_holds = FundHold.objects.filter(
        status__in=[
            FundHold.Status.HELD,
            FundHold.Status.DELIVERY_PENDING,
            FundHold.Status.DELIVERY_CONFIRMED,
            FundHold.Status.DISPUTED,
            FundHold.Status.RELEASE_PENDING,
            FundHold.Status.REFUND_PENDING,
            FundHold.Status.FROZEN,
        ]
    ).aggregate(count=Count("id"), amount=Sum("amount"))
    settlement_totals = Settlement.objects.aggregate(
        pending=Count(
            "id", filter=Q(status__in=[Settlement.Status.PENDING, Settlement.Status.PROCESSING])
        ),
        pending_amount=Sum(
            "net_amount",
            filter=Q(status__in=[Settlement.Status.PENDING, Settlement.Status.PROCESSING]),
        ),
        paid_today=Sum(
            "net_amount",
            filter=Q(status=Settlement.Status.COMPLETED, completed_at__gte=start_of_day),
        ),
    )
    merchant_totals = Merchant.objects.aggregate(
        total=Count("id"), active=Count("id", filter=Q(status="active"))
    )
    verified_merchants = MerchantKYB.objects.filter(
        verified=True, decision="approved"
    ).count()
    open_claims = ProtectionClaim.objects.exclude(
        status__in=[
            ProtectionClaim.Status.WON_CUSTOMER,
            ProtectionClaim.Status.WON_MERCHANT,
            ProtectionClaim.Status.CLOSED,
        ]
    ).count()
    gateway = GatewayConfig.active()
    pending_gateway = GatewayRequest.objects.filter(
        status__in=["pending", "awaiting_approval", "processing"]
    ).count()
    webhook_since = now - timedelta(hours=24)
    webhook_totals = WebhookDelivery.objects.filter(
        updated_at__gte=webhook_since
    ).aggregate(
        total=Count("id"),
        delivered=Count("id", filter=Q(status=WebhookDelivery.Status.DELIVERED)),
        failed=Count("id", filter=Q(status=WebhookDelivery.Status.FAILED)),
        retrying=Count(
            "id",
            filter=Q(
                status__in=[
                    WebhookDelivery.Status.PENDING,
                    WebhookDelivery.Status.RETRYING,
                ]
            ),
        ),
    )
    webhook_rate = (
        round(webhook_totals["delivered"] / webhook_totals["total"] * 100, 1)
        if webhook_totals["total"]
        else 100.0
    )

    chart_start = today - timedelta(days=13)
    daily_rows = {
        row["day"]: row
        for row in successful.filter(created_at__date__gte=chart_start)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(volume=Sum("amount"), count=Count("id"))
        .order_by("day")
    }
    chart_max = max((row["volume"] or ZERO for row in daily_rows.values()), default=ZERO)
    volume_chart = []
    for offset in range(14):
        day = chart_start + timedelta(days=offset)
        row = daily_rows.get(day, {})
        volume = row.get("volume") or ZERO
        volume_chart.append(
            {
                "label": day.strftime("%d %b"),
                "short_label": day.strftime("%d"),
                "volume": _money(volume),
                "short_volume": _short_money(volume),
                "count": row.get("count", 0),
                "height": round((volume / chart_max * 100), 1) if chart_max else 0,
            }
        )

    recent_statuses = Payment.objects.filter(created_at__gte=month_start)
    status_groups = [
        (
            "Protected",
            [Payment.Status.FUNDS_HELD, Payment.Status.DELIVERY_PENDING, Payment.Status.RELEASE_PENDING],
            "green",
        ),
        (
            "Settled",
            [Payment.Status.SETTLED],
            "blue",
        ),
        (
            "Processing",
            [
                Payment.Status.CREATED,
                Payment.Status.ALIAS_VERIFIED,
                Payment.Status.COLLECTION_PENDING,
                Payment.Status.AWAITING_APPROVAL,
                Payment.Status.PROCESSING,
                Payment.Status.SETTLEMENT_PROCESSING,
            ],
            "amber",
        ),
        (
            "Failed / reversed",
            [
                Payment.Status.FAILED,
                Payment.Status.REJECTED,
                Payment.Status.CANCELLED,
                Payment.Status.REVERSED,
                Payment.Status.REFUNDED,
            ],
            "red",
        ),
    ]
    status_counts = [
        {"label": label, "count": recent_statuses.filter(status__in=statuses).count(), "tone": tone}
        for label, statuses, tone in status_groups
    ]
    status_total = sum(item["count"] for item in status_counts)
    for item in status_counts:
        item["percentage"] = round(item["count"] / status_total * 100) if status_total else 0

    context.update(
        {
            "dashboard_generated_at": now,
            "dashboard_greeting": (
                "morning"
                if timezone.localtime(now).hour < 12
                else "afternoon"
                if timezone.localtime(now).hour < 18
                else "evening"
            ),
            "gateway_status": {
                "healthy": bool(gateway),
                "name": gateway.name if gateway else "Not configured",
                "pending": pending_gateway,
                "url": _admin_url("admin:cecf_gatewayconfig_changelist"),
            },
            "stat_cards": [
                {
                    "label": "Payments today",
                    "value": today_totals["count"] or 0,
                    "detail": _money(today_totals["gross"]),
                    "icon": "payments",
                    "tone": "green",
                    "url": _admin_url("admin:payments_payment_changelist"),
                },
                {
                    "label": "Funds protected",
                    "value": _money(active_holds["amount"]),
                    "detail": f'{active_holds["count"] or 0} active holds',
                    "icon": "shield_lock",
                    "tone": "blue",
                    "url": _admin_url("admin:fiduciary_fundhold_changelist"),
                },
                {
                    "label": "Pending settlement",
                    "value": _money(settlement_totals["pending_amount"]),
                    "detail": f'{settlement_totals["pending"] or 0} payouts waiting',
                    "icon": "account_balance",
                    "tone": "amber",
                    "url": _admin_url("admin:settlements_settlement_changelist"),
                },
                {
                    "label": "AmatoPay fees today",
                    "value": _money(today_totals["fees"]),
                    "detail": "Captured fee snapshots",
                    "icon": "percent",
                    "tone": "purple",
                    "url": _admin_url("admin:payments_transactionfee_changelist"),
                },
            ],
            "period_summary": {
                "payments": period_totals["count"] or 0,
                "volume": _money(period_totals["gross"]),
                "fees": _money(period_totals["fees"]),
                "settled_today": _money(settlement_totals["paid_today"]),
            },
            "volume_chart": volume_chart,
            "status_breakdown": status_counts,
            "status_total": status_total,
            "operations": [
                {
                    "label": "Merchants",
                    "value": merchant_totals["total"] or 0,
                    "detail": f'{merchant_totals["active"] or 0} active',
                    "url": _admin_url("admin:merchants_merchant_changelist"),
                },
                {
                    "label": "Verified KYB",
                    "value": verified_merchants,
                    "detail": "Fully approved merchants",
                    "url": _admin_url("admin:merchants_merchantkyb_changelist"),
                },
                {
                    "label": "Open claims",
                    "value": open_claims,
                    "detail": "Require operations review",
                    "url": _admin_url("admin:deliveries_protectionclaim_changelist"),
                },
                {
                    "label": "Gateway queue",
                    "value": pending_gateway,
                    "detail": "Collections and payouts in progress",
                    "url": _admin_url("admin:cecf_gatewayrequest_changelist"),
                },
                {
                    "label": "Webhook health (24h)",
                    "value": f"{webhook_rate}%",
                    "detail": f'{webhook_totals["failed"]} failed · {webhook_totals["retrying"]} queued',
                    "url": _admin_url("admin:webhooks_webhookdelivery_changelist"),
                },
            ],
            "recent_payments": Payment.objects.select_related("merchant")
            .order_by("-created_at")[:8],
        }
    )
    return context
