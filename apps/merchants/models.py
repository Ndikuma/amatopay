import hashlib
import secrets
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from apps.core.models import UUIDModel, TimeStampedModel

User = get_user_model()


def merchant_application_reference():
    return f"AMA-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


class MerchantApplication(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        MORE_INFO = "more_info", "More information required"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class SettlementAliasType(models.TextChoices):
        MOBILE = "MOBILE", "Mobile number"
        ACCOUNT = "ACCOUNT", "BurundiPay account alias"

    reference = models.CharField(
        max_length=30, unique=True, default=merchant_application_reference, editable=False
    )
    legal_name = models.CharField(max_length=200)
    trading_name = models.CharField(max_length=160, blank=True)
    legal_form = models.CharField(max_length=80)
    registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=80, blank=True)
    industry = models.CharField(max_length=120)
    mcc = models.CharField(
        max_length=8,
        blank=True,
        verbose_name="Merchant category code",
        help_text="4-digit MCC if you know it; AmatoPay assigns one otherwise.",
    )
    website = models.URLField(blank=True)
    country = models.CharField(max_length=2, default="BI")
    city = models.CharField(max_length=100)
    address = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=180)
    contact_role = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=40)
    expected_monthly_volume = models.DecimalField(max_digits=20, decimal_places=2)
    expected_monthly_transactions = models.PositiveIntegerField()
    business_description = models.TextField()
    payment_use_case = models.TextField()
    source_of_funds = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where the money your business collects comes from (e.g. product sales, service fees).",
    )
    settlement_alias_type = models.CharField(
        max_length=20,
        choices=SettlementAliasType.choices,
        default=SettlementAliasType.MOBILE,
    )
    settlement_alias = models.CharField(
        max_length=160,
        blank=True,
        help_text="The BurundiPay alias proposed to receive merchant settlements.",
    )
    settlement_account_name = models.CharField(
        max_length=180,
        blank=True,
        help_text="Name registered on the proposed BurundiPay account.",
    )
    statement_descriptor = models.CharField(
        max_length=22,
        blank=True,
        help_text="Short name shown to payers on their statement (max 22 characters).",
    )
    # KYB documents supplied up front so review is the only remaining step.
    registration_document = models.FileField(
        upload_to="merchant_applications/%Y/%m/", blank=True,
        verbose_name="Business registration certificate",
    )
    tax_document = models.FileField(
        upload_to="merchant_applications/%Y/%m/", blank=True,
        verbose_name="Tax / NIF certificate",
    )
    license_document = models.FileField(
        upload_to="merchant_applications/%Y/%m/", blank=True,
        verbose_name="Business licence (if your activity is regulated)",
    )
    address_document = models.FileField(
        upload_to="merchant_applications/%Y/%m/", blank=True,
        verbose_name="Proof of business address",
    )
    id_document = models.FileField(
        upload_to="merchant_applications/%Y/%m/", blank=True,
        verbose_name="Representative ID",
    )
    bank_document = models.FileField(
        upload_to="merchant_applications/%Y/%m/", blank=True,
        verbose_name="Settlement account proof",
    )
    referral_source = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.SUBMITTED, db_index=True
    )
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_merchant_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    consented_at = models.DateTimeField()
    applicant = models.OneToOneField(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merchant_application",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.reference} — {self.legal_name}"


class MerchantApplicationReview(UUIDModel, TimeStampedModel):
    application = models.ForeignKey(
        MerchantApplication, on_delete=models.CASCADE, related_name="review_history"
    )
    previous_status = models.CharField(max_length=24, blank=True)
    new_status = models.CharField(max_length=24)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.application.reference}: {self.previous_status} → {self.new_status}"


class Merchant(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_KYB = "pending_kyb", "Pending KYB"
        UNDER_REVIEW = "under_review", "Under review"
        ACTIVE = "active", "Active"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"

    merchant_code = models.CharField(max_length=50, unique=True)
    legal_name = models.CharField(max_length=200)
    display_name = models.CharField(max_length=160)
    legal_form = models.CharField(max_length=80, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    country = models.CharField(max_length=2, default="BI")
    city = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    mcc = models.CharField(max_length=8, blank=True)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.DRAFT
    )
    risk_rating = models.CharField(max_length=20, default="medium")
    default_currency = models.CharField(max_length=3, default="BIF")
    statement_descriptor = models.CharField(max_length=22, blank=True)
    instant_settlement_enabled = models.BooleanField(
        default=False,
        help_text=(
            "AmatoPay-granted capability. When enabled, this merchant may create "
            "checkout sessions with require_delivery_confirmation=false — funds "
            "auto-release to the merchant as soon as the payment is collected, "
            "with no secure-code delivery gate. Grant only after a risk review."
        ),
    )
    metadata = models.JSONField(default=dict, blank=True)
    owner = models.OneToOneField(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merchant_account",
    )

    def __str__(self):
        return self.display_name


class MerchantKYB(UUIDModel, TimeStampedModel):
    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        MORE_INFO = "more_info", "More information required"

    merchant = models.OneToOneField(
        Merchant, on_delete=models.CASCADE, related_name="kyb"
    )
    decision = models.CharField(
        max_length=20, choices=Decision.choices, default=Decision.PENDING
    )
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=160, blank=True)
    review_notes = models.TextField(blank=True)
    source_of_funds = models.CharField(max_length=200, blank=True)
    expected_monthly_volume = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    expected_monthly_transactions = models.PositiveIntegerField(null=True, blank=True)
    risk_rating = models.CharField(max_length=20, default="medium")


class MerchantDocument(UUIDModel, TimeStampedModel):
    class Type(models.TextChoices):
        REGISTRATION = "registration", "Registration"
        TAX = "tax", "Tax/NIF"
        LICENSE = "license", "Business license"
        ADDRESS = "address", "Proof of address"
        BANK = "bank", "Settlement account proof"
        ID = "id", "Representative ID"
        OTHER = "other", "Other"

    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="kyb_documents"
    )
    document_type = models.CharField(max_length=30, choices=Type.choices)
    document_number = models.CharField(max_length=120, blank=True)
    file = models.FileField(upload_to="merchant_kyb/%Y/%m/", blank=True)
    issued_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    verified = models.BooleanField(default=False)


class MerchantSettlementAccount(UUIDModel, TimeStampedModel):
    class Verification(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        DISABLED = "disabled", "Disabled"

    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="settlement_accounts"
    )
    alias_type = models.CharField(max_length=20, default="MOBILE")
    alias_value = models.CharField(max_length=160)
    account_name = models.CharField(max_length=180, blank=True)
    account_type = models.CharField(max_length=30, blank=True)
    currency = models.CharField(max_length=3, default="BIF")
    provider_customer_reference = models.CharField(max_length=120, blank=True)
    verification_status = models.CharField(
        max_length=20, choices=Verification.choices, default=Verification.PENDING
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    raw_verification = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "alias_type", "alias_value"],
                name="uq_merchant_settlement_alias",
            )
        ]


class MerchantApiKey(UUIDModel, TimeStampedModel):
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=24, db_index=True)
    secret_hash = models.CharField(max_length=64)
    active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)

    @classmethod
    def issue(cls, merchant, name="Default", scopes=None):
        raw = f"sk_{secrets.token_urlsafe(32)}"
        obj = cls.objects.create(
            merchant=merchant,
            name=name,
            prefix=raw[:18],
            secret_hash=hashlib.sha256(raw.encode()).hexdigest(),
            scopes=scopes or ["payments:write", "payments:read"],
        )
        return obj, raw

    def verify(self, raw):
        return secrets.compare_digest(
            self.secret_hash, hashlib.sha256(raw.encode()).hexdigest()
        )

    def rotate(self):
        """Replace this key's secret and return the plaintext exactly once."""
        raw = f"sk_{secrets.token_urlsafe(32)}"
        self.prefix = raw[:18]
        self.secret_hash = hashlib.sha256(raw.encode()).hexdigest()
        self.active = True
        self.last_used_at = None
        self.save(
            update_fields=[
                "prefix",
                "secret_hash",
                "active",
                "last_used_at",
                "updated_at",
            ]
        )
        return raw

    def revoke(self):
        self.active = False
        self.save(update_fields=["active", "updated_at"])


class MerchantWebhookEndpoint(UUIDModel, TimeStampedModel):
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="webhook_endpoints"
    )
    url = models.URLField()
    secret = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    events = models.JSONField(default=list, blank=True)
    description = models.CharField(max_length=160, blank=True)


class MerchantActivity(UUIDModel, TimeStampedModel):
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="activities"
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merchant_activities",
    )
    action = models.CharField(max_length=80)
    description = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "merchant activities"
