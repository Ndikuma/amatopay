from django.contrib import admin
from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from .models import FiduciaryAccount, FundHold, FiduciaryEntry

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
    )
    search_fields = ("creditor_alias", "account_number", "account_name")
    readonly_fields = [field.name for field in FiduciaryAccount._meta.fields]


admin.site.register([FundHold, FiduciaryEntry], ReadOnlyAmatoModelAdmin)
