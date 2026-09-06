import uuid
from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class WebhookEvent(UUIDModel, TimeStampedModel):
    event_id = models.CharField(max_length=80, unique=True, editable=False)
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.CASCADE, related_name="webhook_events"
    )
    type = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict)

    def save(self, *a, **kw):
        if not self.event_id:
            self.event_id = "evt_" + uuid.uuid4().hex
        super().save(*a, **kw)


class WebhookDelivery(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        RETRYING = "retrying", "Retrying"
        FAILED = "failed", "Failed"

    event = models.ForeignKey(
        WebhookEvent, on_delete=models.CASCADE, related_name="deliveries"
    )
    endpoint = models.ForeignKey(
        "merchants.MerchantWebhookEndpoint",
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_status_code = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    last_response_body = models.TextField(
        blank=True,
        help_text="Body the merchant's endpoint returned on the most recent attempt (truncated).",
    )
    last_response_headers = models.JSONField(
        default=dict, blank=True,
        help_text="Response headers from the merchant's endpoint on the most recent attempt.",
    )
    next_retry_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "endpoint"], name="uq_webhook_delivery"
            )
        ]


class WebhookAttempt(UUIDModel, TimeStampedModel):
    """Immutable audit record for one outbound delivery attempt."""

    delivery = models.ForeignKey(
        WebhookDelivery, on_delete=models.CASCADE, related_name="attempt_history"
    )
    attempt_number = models.PositiveSmallIntegerField()
    request_url = models.URLField()
    request_headers = models.JSONField(default=dict)
    request_body = models.JSONField(default=dict)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_headers = models.JSONField(default=dict, blank=True)
    response_body = models.TextField(blank=True)
    error = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    succeeded = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "attempt_number"],
                name="uq_webhook_delivery_attempt",
            )
        ]

    def __str__(self):
        return f"{self.delivery_id} attempt {self.attempt_number}"
