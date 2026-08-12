from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class Refund(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    class Reason(models.TextChoices):
        ORDER_CANCELLED = "order_cancelled", "Order cancelled"
        BILLING_ERROR = "billing_error", "Billing error"
        DELIVERY_FAILED = "delivery_failed", "Delivery failed"
        RETURN = "return", "Returned merchandise"
        FRAUD = "fraud", "Fraud"
        TECHNICAL = "technical", "Technical incident"
        DISPUTE = "dispute", "Protection claim decision"
        OTHER = "other", "Other"

    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, related_name="refunds"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    reason = models.CharField(max_length=30, choices=Reason.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.REQUESTED
    )
    requested_by = models.CharField(max_length=120, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_refund_amount_positive"
            )
        ]
