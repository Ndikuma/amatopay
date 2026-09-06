from django.contrib import admin
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from .models import FiduciaryAccount, FiduciaryEntry, FundHold


class ReadOnlyModelAdmin(ModelAdmin):
    """Rich Unfold presentation for immutable fiduciary records."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(FiduciaryAccount)
class FiduciaryAccountAdmin(ReadOnlyAmatoModelAdmin):
    list_display = (
        "creditor_alias",
        "account_number",
        "account_name",
        "currency",
        "is_verified",
        "active",
        "verified_at",
        "hold_count",
        "total_hold_amount",
    )
    list_filter = ("active", "currency")
    search_fields = ("creditor_alias", "account_number", "account_name")
    readonly_fields = [field.name for field in FiduciaryAccount._meta.fields]
    ordering = ("-created_at",)
    list_per_page = 25

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                hold_count=Count("holds", distinct=True),
                total_hold_amount=Sum("holds__amount"),
            )
        )

    @admin.display(description="Number of holds", ordering="hold_count")
    def hold_count(self, obj):
        return obj.hold_count

    @admin.display(description="Total held amount", ordering="total_hold_amount")
    def total_hold_amount(self, obj):
        amount = obj.total_hold_amount or 0
        return f"{amount:.2f} {obj.currency}"


@admin.register(FundHold)
class FundHoldAdmin(ReadOnlyModelAdmin):
    list_display = (
        "id",
        "payment_link",
        "fiduciary_account_link",
        "amount_display",
        "status_badge",
        "held_at",
        "release_eligible_at",
        "released_at",
        "international",
        "days_held",
    )
    list_filter = (
        "status",
        "international",
        "held_at",
        "released_at",
        "fiduciary_account__currency",
        ("payment__merchant", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "payment__reference",
        "payment__payer_alias",
        "payment__merchant__display_name",
        "fiduciary_account__creditor_alias",
        "fiduciary_account__account_number",
    )
    readonly_fields = (
        "id",
        "payment",
        "fiduciary_account",
        "amount",
        "status",
        "held_at",
        "release_eligible_at",
        "released_at",
        "international",
        "freeze_reason",
        "payment_link",
        "fiduciary_account_link",
        "amount_display",
        "days_held",
        "status_badge",
    )
    fieldsets = (
        ("Payment", {"fields": ("payment", "payment_link", "status", "status_badge")}),
        (
            "Account",
            {"fields": ("fiduciary_account", "fiduciary_account_link", "amount_display")},
        ),
        (
            "Hold details",
            {
                "fields": (
                    "held_at",
                    "release_eligible_at",
                    "released_at",
                    "international",
                    "days_held",
                    "freeze_reason",
                )
            },
        ),
    )
    list_select_related = ("payment", "payment__merchant", "fiduciary_account")
    ordering = ("-held_at",)
    list_per_page = 50
    date_hierarchy = "held_at"

    STATUS_COLORS = {
        FundHold.Status.HELD: "#2196F3",
        FundHold.Status.DELIVERY_PENDING: "#FF9800",
        FundHold.Status.DELIVERY_CONFIRMED: "#4CAF50",
        FundHold.Status.DISPUTED: "#F44336",
        FundHold.Status.RELEASE_PENDING: "#FFC107",
        FundHold.Status.RELEASED: "#2E7D32",
        FundHold.Status.REFUND_PENDING: "#FF9800",
        FundHold.Status.REFUNDED: "#4CAF50",
        FundHold.Status.FROZEN: "#D32F2F",
    }

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return f"{obj.amount:.2f} {obj.fiduciary_account.currency}"

    @admin.display(description="Days held")
    def days_held(self, obj):
        end = obj.released_at or timezone.now()
        return (end - obj.held_at).days

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        color = self.STATUS_COLORS.get(obj.status, "#9E9E9E")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 0.85em; font-weight: 500;">{}</span>',
            color,
            obj.get_status_display(),
        )

    @admin.display(description="Payment", ordering="payment__reference")
    def payment_link(self, obj):
        url = reverse("admin:payments_payment_change", args=[obj.payment_id])
        return format_html('<a href="{}">{}</a>', url, obj.payment.reference or obj.payment_id)

    @admin.display(description="Fiduciary account", ordering="fiduciary_account__creditor_alias")
    def fiduciary_account_link(self, obj):
        url = reverse(
            "admin:fiduciary_fiduciaryaccount_change", args=[obj.fiduciary_account_id]
        )
        return format_html(
            '<a href="{}">{}</a>', url, obj.fiduciary_account.creditor_alias
        )


@admin.register(FiduciaryEntry)
class FiduciaryEntryAdmin(ReadOnlyModelAdmin):
    list_display = (
        "id",
        "account_link",
        "payment_link",
        "direction_badge",
        "kind_badge",
        "amount_display",
        "reference",
        "narrative",
        "created_at",
    )
    list_filter = (
        "direction",
        "kind",
        "created_at",
        ("account", admin.RelatedOnlyFieldListFilter),
        ("payment__merchant", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "reference",
        "narrative",
        "payment__reference",
        "payment__payer_alias",
        "account__creditor_alias",
        "account__account_number",
    )
    readonly_fields = (
        "id",
        "account",
        "payment",
        "direction",
        "kind",
        "amount",
        "reference",
        "narrative",
        "created_at",
        "account_link",
        "payment_link",
        "direction_badge",
        "kind_badge",
        "amount_display",
    )
    fieldsets = (
        (
            "Entry",
            {
                "fields": (
                    "account",
                    "account_link",
                    "payment",
                    "payment_link",
                    "direction_badge",
                    "kind_badge",
                )
            },
        ),
        ("Amount", {"fields": ("amount_display", "reference", "narrative")}),
        ("Metadata", {"fields": ("created_at", "id")}),
    )
    list_select_related = ("account", "payment", "payment__merchant")
    ordering = ("-created_at",)
    list_per_page = 50
    date_hierarchy = "created_at"

    KIND_COLORS = {
        FiduciaryEntry.Kind.CUSTOMER_FUNDS: "#2196F3",
        FiduciaryEntry.Kind.RELEASE: "#4CAF50",
        FiduciaryEntry.Kind.REFUND: "#FF9800",
        FiduciaryEntry.Kind.FEE: "#F44336",
        FiduciaryEntry.Kind.TAX: "#9C27B0",
        FiduciaryEntry.Kind.ADJUSTMENT: "#607D8B",
    }

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return f"{obj.amount:.2f} {obj.account.currency}"

    @admin.display(description="Direction", ordering="direction")
    def direction_badge(self, obj):
        color = {"credit": "#4CAF50", "debit": "#F44336"}.get(obj.direction, "#9E9E9E")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 0.85em; font-weight: 500;">{}</span>',
            color,
            obj.get_direction_display(),
        )

    @admin.display(description="Kind", ordering="kind")
    def kind_badge(self, obj):
        color = self.KIND_COLORS.get(obj.kind, "#9E9E9E")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-size: 0.85em; font-weight: 500;">{}</span>',
            color,
            obj.get_kind_display(),
        )

    @admin.display(description="Account", ordering="account__creditor_alias")
    def account_link(self, obj):
        url = reverse("admin:fiduciary_fiduciaryaccount_change", args=[obj.account_id])
        return format_html('<a href="{}">{}</a>', url, obj.account.creditor_alias)

    @admin.display(description="Payment", ordering="payment__reference")
    def payment_link(self, obj):
        url = reverse("admin:payments_payment_change", args=[obj.payment_id])
        return format_html('<a href="{}">{}</a>', url, obj.payment.reference or obj.payment_id)
