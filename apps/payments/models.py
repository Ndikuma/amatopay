import uuid
from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class Payment(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        ALIAS_VERIFIED = "alias_verified", "Alias verified"
        RTP_PENDING = "rtp_pending", "RTP pending"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        FUNDS_HELD = "funds_held", "Funds held"
        DELIVERY_PENDING = "delivery_pending", "Delivery pending"
        DISPUTED = "disputed", "Disputed"
        RELEASE_PENDING = "release_pending", "Release pending"
        SETTLEMENT_PROCESSING = "settlement_processing", "Settlement processing"
        SETTLED = "settled", "Settled"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        REVERSED = "reversed", "Reversed"
        REFUNDED = "refunded", "Refunded"
        EXPIRED = "expired", "Expired"
        FRAUD_BLOCKED = "fraud_blocked", "Fraud blocked"

    reference = models.CharField(max_length=64, unique=True, editable=False)
    session = models.OneToOneField(
        "checkout.PaymentSession", on_delete=models.PROTECT, related_name="payment"
    )
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="payments"
    )
    payer_alias_type = models.CharField(max_length=20, blank=True)
    payer_alias = models.CharField(max_length=160, blank=True)
    payer_display_name = models.CharField(max_length=180, blank=True)
    payer_reference = models.CharField(max_length=120, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    fee_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    fee_source = models.CharField(max_length=30, blank=True)
    pricing_plan = models.ForeignKey(
        "billing.PricingPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    plan_assignment = models.ForeignKey(
        "billing.MerchantPlanAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    fee_calculated_at = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="BIF")
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.CREATED
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=80, blank=True)
    failure_message = models.CharField(max_length=255, blank=True)
    release_code_hash = models.CharField(max_length=128, blank=True, editable=False)
    release_code_failed_attempts = models.PositiveSmallIntegerField(default=0)
    release_code_locked_at = models.DateTimeField(null=True, blank=True)
    release_code_confirmed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_payment_amount_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(fee_amount__gte=0)
                & models.Q(fee_amount__lt=models.F("amount")),
                name="ck_payment_fee_valid",
            ),
        ]

    @property
    def total_amount(self):
        return self.amount

    @property
    def net_amount(self):
        return self.amount - self.fee_amount

    @property
    def masked_payer_alias(self):
        value = self.payer_alias.strip()
        if not value:
            return ""
        if "@" in value:
            local, domain = value.split("@", 1)
            return f"{local[:1]}•••@{domain}"
        visible = value[-4:]
        return f"••••{visible}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "AMP-PAY-" + uuid.uuid4().hex[:16].upper()
        super().save(*args, **kwargs)


class PaymentStatusHistory(UUIDModel):
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="history"
    )
    status = models.CharField(max_length=30)
    reason = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=40, default="amatopay")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ImmutableTransactionFeeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("Transaction fee snapshots are immutable.")

    def delete(self):
        from django.core.exceptions import ValidationError

        raise ValidationError("Transaction fee snapshots cannot be deleted.")


class TransactionFee(UUIDModel):
    class Source(models.TextChoices):
        PRICING_PLAN = "PRICING_PLAN", "Pricing plan"
        PAY_AS_YOU_GO = "PAY_AS_YOU_GO", "Pay-as-you-go"
        LEGACY = "LEGACY", "Migrated legacy fee"

    transaction = models.OneToOneField(
        Payment, on_delete=models.PROTECT, related_name="transaction_fee"
    )
    gross_amount = models.DecimalField(max_digits=20, decimal_places=2)
    fee_percentage = models.DecimalField(max_digits=7, decimal_places=4)
    fee_amount = models.DecimalField(max_digits=20, decimal_places=2)
    net_amount = models.DecimalField(max_digits=20, decimal_places=2)
    fee_source = models.CharField(max_length=30, choices=Source.choices)
    pricing_plan = models.ForeignKey(
        "billing.PricingPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transaction_fees",
    )
    plan_assignment = models.ForeignKey(
        "billing.MerchantPlanAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transaction_fees",
    )
    calculated_at = models.DateTimeField()
    objects = models.Manager.from_queryset(ImmutableTransactionFeeQuerySet)()

    class Meta:
        ordering = ["-calculated_at"]
        indexes = [
            models.Index(fields=["fee_source", "calculated_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(gross_amount__gt=0)
                & models.Q(fee_amount__gte=0)
                & models.Q(net_amount__gt=0),
                name="ck_transaction_fee_amounts",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    gross_amount=models.F("fee_amount") + models.F("net_amount")
                ),
                name="ck_transaction_fee_balanced",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            from django.core.exceptions import ValidationError

            raise ValidationError("Transaction fee snapshots are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("Transaction fee snapshots cannot be deleted.")


class IdempotencyRecord(UUIDModel, TimeStampedModel):
    key = models.CharField(max_length=160, unique=True)
    scope = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64)
    response_code = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)
