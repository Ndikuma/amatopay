from django.contrib import admin
from unfold.admin import ModelAdmin
from django.urls import reverse
from django.utils.html import format_html

from apps.core.models import AuditEvent
from apps.payments.models import TransactionFee

from .models import (
    MerchantPlanAssignment,
    PricingPlan,
)


def _audit_change(request, obj, action, previous):
    previous = {key: str(value) for key, value in previous.items()}
    latest_event = AuditEvent.objects.order_by("-created_at").first()
    current = {
        field: str(getattr(obj, field))
        for field in (
            "currency",
            "included_transactions_per_month",
            "contracted_transactions_per_month",
            "monthly_price",
            "contracted_monthly_price",
            "plan_id",
            "active",
            "effective_from",
            "effective_until",
        )
        if hasattr(obj, field)
    }
    AuditEvent.objects.create(
        actor=request.user.get_username(),
        action=action,
        object_type=obj._meta.label,
        object_id=str(obj.pk),
        previous_hash=latest_event.event_hash if latest_event else "",
        payload={
            "previous": previous,
            "new": current,
            "reason": getattr(obj, "change_reason", "") or getattr(obj, "reason", ""),
        },
    )


@admin.register(PricingPlan)
class PricingPlanAdmin(ModelAdmin):
    list_display = (
        "name",
        "code",
        "included_transactions_per_month",
        "monthly_price",
        "currency",
        "active",
    )
    list_filter = ("active", "currency")
    search_fields = ("name", "code", "description")

    def save_model(self, request, obj, form, change):
        previous = {}
        if change:
            previous = type(obj).objects.filter(pk=obj.pk).values().first() or {}
        super().save_model(request, obj, form, change)
        _audit_change(
            request, obj, "pricing_plan.updated" if change else "pricing_plan.created", previous
        )


@admin.register(MerchantPlanAssignment)
class MerchantPlanAssignmentAdmin(ModelAdmin):
    list_display = (
        "merchant",
        "plan",
        "active",
        "effective_from",
        "effective_until",
        "monthly_transaction_limit",
        "effective_monthly_price",
        "assigned_by",
    )
    list_filter = ("active", "plan")
    search_fields = ("merchant__display_name", "merchant__merchant_code", "reason")
    autocomplete_fields = ("merchant", "plan")
    readonly_fields = ("assigned_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        previous = {}
        if change:
            previous = type(obj).objects.filter(pk=obj.pk).values().first() or {}
        elif not obj.assigned_by_id:
            obj.assigned_by = request.user
        super().save_model(request, obj, form, change)
        _audit_change(
            request,
            obj,
            "merchant_plan.updated" if change else "merchant_plan.assigned",
            previous,
        )


@admin.register(TransactionFee)
class TransactionFeeAdmin(ModelAdmin):
    list_display = (
        "transaction",
        "gross_amount",
        "fee_percentage",
        "fee_amount",
        "net_amount",
        "fee_source",
        "pricing_plan",
        "calculated_at",
    )
    list_filter = ("fee_source", "pricing_plan")
    search_fields = ("transaction__reference", "transaction__merchant__display_name")
    readonly_fields = [field.name for field in TransactionFee._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
