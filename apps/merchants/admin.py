from django.contrib import admin
from django.db import models
from django.utils import timezone
from unfold.admin import ModelAdmin
from django.contrib import messages
from apps.gateway import client as gateway_client

from apps.billing.models import (
    MerchantPlanAssignment,
)
from apps.billing.services import resolve_transaction_fee
from apps.core.admin_base import AmatoModelAdmin

from .models import (
    Merchant,
    MerchantApplication,
    MerchantApplicationReview,
    MerchantActivity,
    MerchantApiKey,
    MerchantDocument,
    MerchantKYB,
    MerchantSettlementAccount,
    MerchantWebhookEndpoint,
)


class MerchantApplicationReviewInline(admin.TabularInline):
    model = MerchantApplicationReview
    extra = 0
    can_delete = False
    readonly_fields = ("previous_status", "new_status", "note", "actor", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MerchantApplication)
class MerchantApplicationAdmin(ModelAdmin):
    list_display = ("reference", "legal_name", "contact_name", "phone", "status", "created_at")
    list_filter = ("status", "country", "industry", "created_at")
    search_fields = ("reference", "legal_name", "trading_name", "email", "phone", "registration_number", "tax_id")
    readonly_fields = (
        "reference", "applicant", "source_ip", "user_agent", "consented_at", "created_at",
        "updated_at", "reviewed_by", "reviewed_at",
    )
    fieldsets = (
        ("Application", {"fields": ("reference", "applicant", "status", "legal_name", "trading_name", "legal_form", "industry", "mcc", "business_description", "payment_use_case", "source_of_funds")}),
        ("Registration", {"fields": ("registration_number", "tax_id", "website", "country", "city", "address")}),
        ("Primary contact", {"fields": ("contact_name", "contact_role", "email", "phone")}),
        ("Expected activity", {"fields": ("expected_monthly_volume", "expected_monthly_transactions", "referral_source")}),
        ("Proposed BurundiPay settlement", {"description": "Applicant-provided mobile alias. Verify it before enabling settlements.", "fields": ("settlement_alias", "settlement_account_name", "statement_descriptor")}),
        ("KYB documents", {"fields": ("registration_document", "tax_document", "license_document", "address_document", "id_document", "bank_document")}),
        ("Review", {"fields": ("review_notes", "reviewed_by", "reviewed_at")}),
        ("Submission evidence", {"classes": ("collapse",), "fields": ("source_ip", "user_agent", "consented_at", "created_at", "updated_at")}),
    )
    inlines = (MerchantApplicationReviewInline,)

    def save_model(self, request, obj, form, change):
        previous = None
        if change:
            previous = MerchantApplication.objects.get(pk=obj.pk).status
        if previous != obj.status:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
        if previous != obj.status:
            MerchantApplicationReview.objects.create(
                application=obj,
                previous_status=previous or "",
                new_status=obj.status,
                note=obj.review_notes,
                actor=request.user,
            )


@admin.register(MerchantApplicationReview)
class MerchantApplicationReviewAdmin(ModelAdmin):
    list_display = ("created_at", "application", "previous_status", "new_status", "actor")
    list_filter = ("new_status", "created_at")
    search_fields = ("application__reference", "application__legal_name", "note")
    readonly_fields = ("application", "previous_status", "new_status", "note", "actor", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Merchant)
class MerchantAdmin(ModelAdmin):
    list_display = (
        "merchant_code",
        "display_name",
        "status",
        "kyc_status",
        "kyb_status",
        "verification_level",
        "pricing_plan",
        "default_fee",
        "effective_fee",
    )
    list_filter = ("status", "country", "risk_rating", "instant_settlement_enabled")
    search_fields = ("merchant_code", "legal_name", "display_name", "email")

    @admin.display(description="KYC status")
    def kyc_status(self, obj):
        document = obj.kyb_documents.filter(
            document_type=MerchantDocument.Type.ID, verified=True
        ).first()
        if not document:
            return "Partial"
        if document.expires_at and document.expires_at < timezone.localdate():
            return "Expired"
        return "Verified"

    @admin.display(description="KYB status")
    def kyb_status(self, obj):
        try:
            return obj.kyb.get_decision_display()
        except MerchantKYB.DoesNotExist:
            return "Incomplete"

    @admin.display(description="Verification level")
    def verification_level(self, obj):
        try:
            from apps.merchants.models import MerchantKYB
            kyb = obj.kyb
            return "Verified" if kyb.verified and kyb.decision == MerchantKYB.Decision.APPROVED else "Partial"
        except Exception:
            return "Partial"

    @admin.display(description="Default fee")
    def default_fee(self, obj):
        try:
            from apps.billing.services import _payg_plan
            plan = _payg_plan(obj.default_currency)
            return f"{plan.transaction_fee_percentage}%" if plan else "Not configured"
        except Exception:
            return "Not configured"

    @admin.display(description="Pricing plan")
    def pricing_plan(self, obj):
        now = timezone.now()
        assignment = (
            MerchantPlanAssignment.objects.filter(
                merchant=obj,
                plan__active=True,
                active=True,
                effective_from__lte=now,
            )
            .filter(
                models.Q(effective_until__isnull=True)
                | models.Q(effective_until__gt=now)
            )
            .select_related("plan")
            .order_by("-effective_from")
            .first()
        )
        if assignment:
            return assignment.plan.name
        return "Pay-as-you-go fees"

    @admin.display(description="Effective fee")
    def effective_fee(self, obj):
        try:
            return f"{resolve_transaction_fee(obj, 100).fee_percentage}%"
        except Exception:
            return "Not configured"


admin.site.register(
    [
        MerchantKYB,
        MerchantDocument,
        MerchantApiKey,
        MerchantWebhookEndpoint,
    ],
    AmatoModelAdmin,
)


@admin.register(MerchantSettlementAccount)
class MerchantSettlementAccountAdmin(ModelAdmin):
    list_display = ("merchant", "account_name", "alias_value", "currency", "verification_status", "is_primary", "is_active")
    list_filter = ("verification_status", "currency", "is_primary", "is_active")
    search_fields = ("merchant__merchant_code", "merchant__display_name", "alias_value", "account_name")
    actions = ("verify_selected_aliases",)

    @admin.action(description="Verify selected MOBILE aliases with the gateway")
    def verify_selected_aliases(self, request, queryset):
        verified = 0
        failed = 0
        for account in queryset:
            result = gateway_client.verify_alias(
                {
                    "requestId": f"AMP-MER-ALIAS-{account.id.hex[:16].upper()}",
                    "alias": account.alias_value,
                    "aliasType": "MOBILE",
                }
            )
            customer = result.get("customer") or {}
            gateway_account = result.get("account") or {}
            account.raw_verification = result
            if result.get("found") and str(result.get("status", "")).upper() == "ACTIVE":
                account.alias_type = "MOBILE"
                account.verification_status = account.Verification.VERIFIED
                account.account_name = customer.get("name", "")
                account.provider_customer_reference = customer.get("reference", "")
                account.account_type = gateway_account.get("type", "MOBILE")
                account.currency = gateway_account.get("currency", account.currency)
                account.verified_at = timezone.now()
                verified += 1
            else:
                account.verification_status = account.Verification.FAILED
                account.verified_at = None
                failed += 1
            account.save()
        self.message_user(
            request,
            f"Verified {verified} settlement alias(es); {failed} failed verification.",
            messages.SUCCESS if not failed else messages.WARNING,
        )


@admin.register(MerchantActivity)
class MerchantActivityAdmin(ModelAdmin):
    list_display = ("created_at", "merchant", "actor", "action", "ip_address")
    list_filter = ("action", "merchant")
    search_fields = ("description", "actor__email", "merchant__display_name")
    readonly_fields = (
        "merchant",
        "actor",
        "action",
        "description",
        "ip_address",
        "metadata",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
