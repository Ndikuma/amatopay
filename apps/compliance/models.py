from django.conf import settings
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
    class Status(models.TextChoices):
        GENERATED = "generated", "Generated"
        REVIEWED = "reviewed", "Reviewed"
        SUBMITTED = "submitted", "Submitted"
        ARCHIVED = "archived", "Archived"

    report_type = models.CharField(
        max_length=80,
        help_text="One of the report generators registered in compliance.reports.",
    )
    title = models.CharField(max_length=200, blank=True, editable=False)
    period_start = models.DateField()
    period_end = models.DateField()
    payload = models.JSONField(
        default=dict, editable=False,
        help_text="Frozen snapshot: {columns, rows, summary, generated_at}.",
    )
    row_count = models.PositiveIntegerField(default=0, editable=False)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.GENERATED
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_regulatory_reports",
        editable=False,
    )
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"{self.report_type} · {self.period_start}–{self.period_end}"


class DataRetentionRecord(UUIDModel, TimeStampedModel):
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=100)
    retain_until = models.DateField()
    legal_basis = models.CharField(max_length=160, default="BRB Circular 008/SP/2026")
    archived = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
