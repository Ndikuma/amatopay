from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class SuspiciousTransaction(UUIDModel, TimeStampedModel):
    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, related_name="suspicious_reports"
    )
    reason = models.TextField()
    indicators = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=30, default="open")
    reported_to_brb = models.BooleanField(default=False)
    reported_to_cnrf = models.BooleanField(default=False)
    reported_at = models.DateTimeField(null=True, blank=True)


class RegulatoryReport(UUIDModel, TimeStampedModel):
    report_type = models.CharField(max_length=80)
    period_start = models.DateField()
    period_end = models.DateField()
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)


class DataRetentionRecord(UUIDModel, TimeStampedModel):
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=100)
    retain_until = models.DateField()
    legal_basis = models.CharField(max_length=160, default="BRB Circular 008/SP/2026")
    archived = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
