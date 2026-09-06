from django.contrib import admin

from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from apps.fiduciary.inlines import FiduciaryEntryInline, FundHoldInline
from .models import IdempotencyRecord, Payment, PaymentStatusHistory


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAmatoModelAdmin):
    list_display = (
        "reference",
        "merchant",
        "amount",
        "fee_amount",
        "currency",
        "status",
        "created_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("reference", "provider_reference", "payer_alias", "payer_display_name")
    date_hierarchy = "created_at"
    inlines = (FundHoldInline, FiduciaryEntryInline)


admin.site.register(
    [PaymentStatusHistory, IdempotencyRecord],
    ReadOnlyAmatoModelAdmin,
)
