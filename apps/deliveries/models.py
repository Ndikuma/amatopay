from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class Delivery(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SHIPPED = "shipped", "Shipped"
        UNDER_REVIEW = "under_review", "Under review"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="delivery"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    merchant_reference = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    evidence = models.JSONField(default=dict, blank=True)


class DeliveryConfirmation(UUIDModel, TimeStampedModel):
    class Decision(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        DISPUTED = "disputed", "Disputed"
        REVIEW = "review", "Manual review"

    class Method(models.TextChoices):
        PAYER_SECURE_CODE = "payer_secure_code", "Secure delivery code"
        VERIFIED_PAYER_ALIAS = "verified_payer_alias", "Verified payer alias"
        MERCHANT_EVIDENCE = "merchant_evidence", "Merchant evidence"
        OPERATIONS_REVIEW = "operations_review", "Operations review"

    delivery = models.OneToOneField(
        Delivery, on_delete=models.PROTECT, related_name="confirmation"
    )
    decision = models.CharField(max_length=20, choices=Decision.choices)
    confirmed_by = models.CharField(max_length=120, blank=True)
    method = models.CharField(max_length=40, choices=Method.choices, blank=True)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)


class ProtectionClaim(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        UNDER_REVIEW = "under_review", "Under review"
        MEDIATION = "mediation", "Mediation"
        ARBITRATION = "arbitration", "Arbitration"
        WON_CUSTOMER = "won_customer", "Resolved for payer"
        WON_MERCHANT = "won_merchant", "Resolved for merchant"
        CLOSED = "closed", "Closed"

    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, related_name="protection_claims"
    )
    reason = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.OPEN
    )
    opened_by = models.CharField(max_length=120, blank=True)
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "disputes_dispute"


class ProtectionClaimEvidence(UUIDModel, TimeStampedModel):
    claim = models.ForeignKey(
        ProtectionClaim,
        on_delete=models.CASCADE,
        related_name="evidence_items",
        db_column="dispute_id",
    )
    submitted_by = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="protection-claims/%Y/%m/", blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "disputes_disputeevidence"


class ProtectionClaimEvent(UUIDModel, TimeStampedModel):
    claim = models.ForeignKey(
        ProtectionClaim,
        on_delete=models.CASCADE,
        related_name="events",
        db_column="dispute_id",
    )
    action = models.CharField(max_length=80)
    actor = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "disputes_disputeevent"
