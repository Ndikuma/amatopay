from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class IdempotencyKey(UUIDModel, TimeStampedModel):
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.CASCADE, related_name="idempotency_keys"
    )
    key = models.CharField(max_length=160)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "key"], name="uq_merchant_idempotency"
            )
        ]
