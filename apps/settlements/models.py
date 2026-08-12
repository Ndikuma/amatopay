import uuid
from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class SettlementBatch(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    business_date = models.DateField()
    currency = models.CharField(max_length=3, default="BIF")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    total_gross = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_fees = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_net = models.DecimalField(max_digits=20, decimal_places=2, default=0)


class Settlement(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=64, unique=True, editable=False)
    batch = models.ForeignKey(
        SettlementBatch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="settlements",
    )
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="settlements"
    )
    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="settlement"
    )
    gross_amount = models.DecimalField(max_digits=20, decimal_places=2)
    gateway_fee = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    merchant_fee = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=20, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    beneficiary_alias = models.CharField(max_length=160, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    failure_code = models.CharField(max_length=80, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(gross_amount__gt=0)
                & models.Q(merchant_fee__gte=0)
                & models.Q(refund_amount__gte=0)
                & models.Q(net_amount__gte=0),
                name="ck_settlement_amounts_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    gross_amount=(
                        models.F("merchant_fee")
                        + models.F("refund_amount")
                        + models.F("net_amount")
                    )
                ),
                name="ck_settlement_balanced",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "AMP-STL-" + uuid.uuid4().hex[:16].upper()
        super().save(*args, **kwargs)
