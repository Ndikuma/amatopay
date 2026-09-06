"""Point-in-time compliance / regulatory reports.

Each report is a pure function of a date range that returns a :class:`ReportData`
snapshot (column headers + rows + a summary). The snapshot is stored on
``RegulatoryReport.payload`` when generated from the admin, so a report never
changes after the fact — it can be re-exported to CSV or PDF at any time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from django.db.models import Count, Sum


@dataclass
class ReportData:
    columns: list[str]
    rows: list[list]
    summary: dict = field(default_factory=dict)


REPORTS: dict[str, dict] = {}


def register(key: str, label: str, description: str = ""):
    def wrapper(fn: Callable):
        REPORTS[key] = {"key": key, "label": label, "description": description, "fn": fn}
        return fn

    return wrapper


def report_choices() -> list[tuple[str, str]]:
    return [(key, meta["label"]) for key, meta in sorted(REPORTS.items())]


def generate(key: str, period_start, period_end) -> ReportData:
    meta = REPORTS.get(key)
    if not meta:
        raise KeyError(f"Unknown report type: {key}")
    return meta["fn"](period_start, period_end)


def _money(value) -> str:
    return f"{(value or Decimal('0')):.2f}"


def _dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _date_range(qs, field_name, start, end):
    return qs.filter(
        **{f"{field_name}__date__gte": start, f"{field_name}__date__lte": end}
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@register("transactions", "Transactions", "Every payment created in the period.")
def _transactions(start, end):
    from apps.payments.models import Payment

    qs = (
        _date_range(Payment.objects.all(), "created_at", start, end)
        .select_related("merchant", "session")
        .order_by("created_at")
    )
    rows = [
        [
            p.reference,
            p.merchant.merchant_code,
            p.merchant.display_name,
            p.session.order_number if p.session_id else "",
            _money(p.amount),
            _money(p.fee_amount),
            _money(p.net_amount),
            p.currency,
            p.get_status_display(),
            _dt(p.created_at),
            _dt(p.paid_at),
        ]
        for p in qs
    ]
    agg = qs.aggregate(gross=Sum("amount"), fees=Sum("fee_amount"))
    paid = qs.filter(status=Payment.Status.SETTLED).count()
    return ReportData(
        columns=[
            "Reference", "Merchant code", "Merchant", "Order",
            "Gross", "Fee", "Net", "Currency", "Status", "Created", "Paid at",
        ],
        rows=rows,
        summary={
            "count": qs.count(),
            "settled_count": paid,
            "gross_total": _money(agg["gross"]),
            "fee_total": _money(agg["fees"]),
        },
    )


@register("settlements", "Settlements", "Merchant settlements in the period.")
def _settlements(start, end):
    from apps.settlements.models import Settlement

    qs = (
        _date_range(Settlement.objects.all(), "created_at", start, end)
        .select_related("merchant", "payment")
        .order_by("created_at")
    )
    rows = [
        [
            s.reference,
            s.merchant.merchant_code,
            s.merchant.display_name,
            s.payment.reference,
            _money(s.gross_amount),
            _money(s.merchant_fee),
            _money(s.refund_amount),
            _money(s.net_amount),
            s.get_status_display(),
            s.beneficiary_alias,
            _dt(s.completed_at),
        ]
        for s in qs
    ]
    agg = qs.aggregate(gross=Sum("gross_amount"), net=Sum("net_amount"), fees=Sum("merchant_fee"))
    return ReportData(
        columns=[
            "Reference", "Merchant code", "Merchant", "Payment",
            "Gross", "Fee", "Refunds", "Net", "Status", "Beneficiary alias", "Completed",
        ],
        rows=rows,
        summary={
            "count": qs.count(),
            "completed_count": qs.filter(status=Settlement.Status.COMPLETED).count(),
            "gross_total": _money(agg["gross"]),
            "net_total": _money(agg["net"]),
            "fee_total": _money(agg["fees"]),
        },
    )


@register("fee_income", "Fee income", "AmatoPay transaction-fee snapshots in the period.")
def _fee_income(start, end):
    from apps.payments.models import TransactionFee

    qs = (
        _date_range(TransactionFee.objects.all(), "calculated_at", start, end)
        .select_related("transaction", "transaction__merchant", "pricing_plan")
        .order_by("calculated_at")
    )
    rows = [
        [
            f.transaction.reference,
            f.transaction.merchant.display_name,
            _money(f.gross_amount),
            f"{f.fee_percentage:.4f}",
            _money(f.fee_amount),
            _money(f.net_amount),
            f.get_fee_source_display(),
            f.pricing_plan.code if f.pricing_plan_id else "",
            _dt(f.calculated_at),
        ]
        for f in qs
    ]
    agg = qs.aggregate(gross=Sum("gross_amount"), fees=Sum("fee_amount"))
    return ReportData(
        columns=[
            "Payment", "Merchant", "Gross", "Fee %", "Fee", "Net",
            "Fee source", "Plan", "Calculated at",
        ],
        rows=rows,
        summary={
            "count": qs.count(),
            "gross_total": _money(agg["gross"]),
            "fee_total": _money(agg["fees"]),
        },
    )


@register("protected_funds", "Protected funds", "Fiduciary holds opened in the period.")
def _protected_funds(start, end):
    from apps.fiduciary.models import FundHold

    qs = (
        _date_range(FundHold.objects.all(), "held_at", start, end)
        .select_related("payment", "payment__merchant", "fiduciary_account")
        .order_by("held_at")
    )
    rows = [
        [
            h.payment.reference,
            h.payment.merchant.display_name,
            _money(h.amount),
            h.fiduciary_account.currency,
            h.get_status_display(),
            "International" if h.international else "Domestic",
            _dt(h.held_at),
            _dt(h.release_eligible_at),
            _dt(h.released_at),
        ]
        for h in qs
    ]
    still_held = qs.exclude(status__in=["released", "refunded"])
    agg = still_held.aggregate(total=Sum("amount"))
    return ReportData(
        columns=[
            "Payment", "Merchant", "Amount", "Currency", "Status", "Scope",
            "Held at", "Release eligible", "Released at",
        ],
        rows=rows,
        summary={
            "count": qs.count(),
            "still_held_count": still_held.count(),
            "still_held_total": _money(agg["total"]),
        },
    )


@register(
    "suspicious_activity",
    "Suspicious activity",
    "Suspicious transaction reports raised in the period (for BRB / CNRF).",
)
def _suspicious_activity(start, end):
    from apps.compliance.models import SuspiciousTransaction

    qs = (
        _date_range(SuspiciousTransaction.objects.all(), "created_at", start, end)
        .select_related("payment", "payment__merchant")
        .order_by("created_at")
    )
    rows = [
        [
            s.payment.reference,
            s.payment.merchant.display_name,
            _money(s.payment.amount),
            s.payment.currency,
            s.status,
            ", ".join(str(i) for i in (s.indicators or [])),
            "yes" if s.reported_to_brb else "no",
            "yes" if s.reported_to_cnrf else "no",
            _dt(s.reported_at),
            (s.reason or "").replace("\n", " ")[:400],
        ]
        for s in qs
    ]
    return ReportData(
        columns=[
            "Payment", "Merchant", "Amount", "Currency", "Status", "Indicators",
            "Reported BRB", "Reported CNRF", "Reported at", "Reason",
        ],
        rows=rows,
        summary={
            "count": qs.count(),
            "open_count": qs.filter(status="open").count(),
            "reported_brb_count": qs.filter(reported_to_brb=True).count(),
            "reported_cnrf_count": qs.filter(reported_to_cnrf=True).count(),
        },
    )


@register(
    "merchant_onboarding",
    "Merchant onboarding",
    "Merchant applications and their review outcome in the period.",
)
def _merchant_onboarding(start, end):
    from apps.merchants.models import MerchantApplication

    qs = _date_range(
        MerchantApplication.objects.all(), "created_at", start, end
    ).order_by("created_at")
    rows = [
        [
            a.reference,
            a.legal_name,
            a.trading_name,
            a.country,
            a.industry,
            _money(a.expected_monthly_volume),
            a.expected_monthly_transactions,
            a.get_status_display(),
            a.reviewed_by.get_username() if a.reviewed_by_id else "",
            _dt(a.reviewed_at),
            _dt(a.created_at),
        ]
        for a in qs
    ]
    by_status = dict(
        qs.values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    return ReportData(
        columns=[
            "Reference", "Legal name", "Trading name", "Country", "Industry",
            "Expected volume", "Expected txns", "Status", "Reviewed by",
            "Reviewed at", "Submitted",
        ],
        rows=rows,
        summary={"count": qs.count(), "by_status": by_status},
    )


@register("data_retention", "Data retention", "Retention schedule records.")
def _data_retention(start, end):
    from apps.compliance.models import DataRetentionRecord

    qs = _date_range(
        DataRetentionRecord.objects.all(), "created_at", start, end
    ).order_by("retain_until")
    rows = [
        [
            r.object_type,
            r.object_id,
            r.retain_until.isoformat(),
            r.legal_basis,
            "yes" if r.archived else "no",
            _dt(r.deleted_at),
        ]
        for r in qs
    ]
    return ReportData(
        columns=["Object type", "Object id", "Retain until", "Legal basis", "Archived", "Deleted at"],
        rows=rows,
        summary={
            "count": qs.count(),
            "archived_count": qs.filter(archived=True).count(),
        },
    )
