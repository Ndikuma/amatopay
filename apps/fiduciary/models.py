from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class FiduciaryAccount(UUIDModel, TimeStampedModel):
    singleton_key = models.CharField(
        max_length=20, default="AMATOPAY", unique=True, editable=False
    )
    alias_type = models.CharField(max_length=20, default="MOBILE", editable=False)
    creditor_alias = models.CharField(
        max_length=160, unique=True, editable=False, default=""
    )
    account_number = models.CharField(
        max_length=120, unique=True, editable=False, default=""
    )
    account_name = models.CharField(max_length=180, blank=True)
    currency = models.CharField(max_length=3, default="BIF")
    active = models.BooleanField(default=True)
    verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    raw_verification = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        verbose_name = "AmatoPay fiduciary account"
        verbose_name_plural = "AmatoPay fiduciary account"

    @property
    def is_verified(self):
        return self.verified_at is not None

    def __str__(self):
        return f"{self.account_name or 'AmatoPay fiduciary'} · {self.creditor_alias}"


class FiduciaryQRCode(UUIDModel, TimeStampedModel):
    """AmatoPay's own registered QR code at the gateway — one per fiduciary account.

    Synced from a full ``qr.scan()`` response (see
    ``apps.fiduciary.services.sync_fiduciary_qr_code``). Unlike
    ``cecf.QRPaymentWatch`` (ephemeral, one row per payment, only the two
    UUIDs needed to poll), this is the single durable record of what's
    actually registered at the gateway — its lock state, TTL, and full
    creditor/remittance detail — so ops can see and track it directly.
    """

    singleton_key = models.CharField(
        max_length=20, default="AMATOPAY", unique=True, editable=False
    )

    provider_row_id = models.CharField(max_length=40, blank=True)
    qr_header_uuid = models.CharField(max_length=120, blank=True, db_index=True)
    qr_extension_uuid = models.CharField(max_length=120, blank=True)
    qr_type = models.CharField(max_length=20, blank=True)
    amount_type = models.CharField(max_length=20, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    pmt_context = models.CharField(max_length=40, blank=True)
    iso_ver = models.PositiveSmallIntegerField(null=True, blank=True)
    qr_as_text = models.TextField(blank=True)
    qr_as_image = models.TextField(blank=True, help_text="Base64 image, if the gateway supplies one.")
    status = models.CharField(max_length=30, blank=True)
    provider_created_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    creditor_alias = models.CharField(max_length=160, blank=True)
    merchant_code = models.CharField(max_length=60, blank=True)
    sync_message = models.CharField(max_length=255, blank=True)
    is_locked = models.BooleanField(default=False)
    lock_ttl = models.PositiveIntegerField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=160, blank=True)
    lock_expires_at = models.DateTimeField(null=True, blank=True)
    lock_release_required = models.BooleanField(default=False)
    ttl_length = models.PositiveIntegerField(null=True, blank=True)
    ttl_units = models.CharField(max_length=20, blank=True)
    creditor_name = models.CharField(max_length=180, blank=True)
    creditor_account = models.CharField(max_length=120, blank=True)
    creditor_agent_bic = models.CharField(max_length=20, blank=True)
    creditor_agent_code_type = models.CharField(max_length=20, blank=True)
    is_our_institution = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    amount_min = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    amount_max = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dba = models.CharField(max_length=180, blank=True)
    end_to_end = models.CharField(max_length=80, blank=True)
    mcc = models.CharField(max_length=10, blank=True)
    bank_op_code = models.CharField(max_length=20, blank=True)
    ttc = models.CharField(max_length=20, blank=True)
    creditor_ref = models.CharField(max_length=120, blank=True)
    customer_type = models.CharField(max_length=30, blank=True)
    tax_id = models.CharField(max_length=40, blank=True)
    country_of_residence = models.CharField(max_length=5, blank=True)
    redirect_url = models.URLField(max_length=500, blank=True)
    remittance_info = models.CharField(max_length=255, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "AmatoPay fiduciary QR code"
        verbose_name_plural = "AmatoPay fiduciary QR code"

    def __str__(self):
        return f"{self.creditor_alias or 'AmatoPay QR'} · {self.qr_header_uuid or 'unsynced'}"


class FiduciaryQRExtension(UUIDModel):
    """One ``extensions[]`` entry from the last QR sync — each has its own UUID/TTL."""

    qr_code = models.ForeignKey(
        FiduciaryQRCode, on_delete=models.CASCADE, related_name="extensions"
    )
    provider_row_id = models.CharField(max_length=40, blank=True)
    qr_extension_uuid = models.CharField(max_length=120, blank=True, db_index=True)
    is_last = models.BooleanField(default=False)
    status = models.CharField(max_length=30, blank=True)
    creditor_name = models.CharField(max_length=180, blank=True)
    creditor_account = models.CharField(max_length=120, blank=True)
    creditor_agent_bic = models.CharField(max_length=20, blank=True)
    creditor_agent_code_type = models.CharField(max_length=20, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    amount_min = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    amount_max = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    dba = models.CharField(max_length=180, blank=True)
    end_to_end = models.CharField(max_length=80, blank=True)
    mcc = models.CharField(max_length=10, blank=True)
    bank_op_code = models.CharField(max_length=20, blank=True)
    ttc = models.CharField(max_length=20, blank=True)
    remittance_info = models.CharField(max_length=255, blank=True)
    creditor_ref = models.CharField(max_length=120, blank=True)
    ttl_length = models.PositiveIntegerField(null=True, blank=True)
    ttl_units = models.CharField(max_length=20, blank=True)
    provider_created_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["qr_code", "qr_extension_uuid"],
                condition=~models.Q(qr_extension_uuid=""),
                name="uq_fiduciary_qr_extension_uuid",
            )
        ]

    def __str__(self):
        return self.qr_extension_uuid or str(self.pk)


class FundHold(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        HELD = "held", "Held"
        DELIVERY_PENDING = "delivery_pending", "Delivery pending"
        DELIVERY_CONFIRMED = "delivery_confirmed", "Delivery confirmed"
        DISPUTED = "disputed", "Disputed"
        RELEASE_PENDING = "release_pending", "Release pending"
        RELEASED = "released", "Released"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REFUNDED = "refunded", "Refunded"
        FROZEN = "frozen", "Frozen"

    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="fund_hold"
    )
    fiduciary_account = models.ForeignKey(
        FiduciaryAccount, on_delete=models.PROTECT, related_name="holds"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.HELD
    )
    held_at = models.DateTimeField(auto_now_add=True)
    release_eligible_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    international = models.BooleanField(default=False)
    freeze_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_fund_hold_amount_positive"
            )
        ]


class FiduciaryEntry(UUIDModel):
    class Direction(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    class Kind(models.TextChoices):
        CUSTOMER_FUNDS = "customer_funds", "Customer funds"
        RELEASE = "release", "Release"
        REFUND = "refund", "Refund"
        FEE = "fee", "Fee"
        TAX = "tax", "Tax"
        ADJUSTMENT = "adjustment", "Adjustment"

    account = models.ForeignKey(
        FiduciaryAccount, on_delete=models.PROTECT, related_name="entries"
    )
    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, related_name="fiduciary_entries"
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    kind = models.CharField(
        max_length=30, choices=Kind.choices, default=Kind.CUSTOMER_FUNDS
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    reference = models.CharField(max_length=120)
    narrative = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_fiduciary_entry_positive"
            ),
            models.UniqueConstraint(
                fields=["payment", "kind", "reference"],
                name="uq_fiduciary_payment_kind_reference",
            ),
        ]
