import uuid
import hashlib
import json
from django.db import models


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditEvent(UUIDModel, TimeStampedModel):
    actor = models.CharField(max_length=160, blank=True)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    request_id = models.CharField(max_length=100, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    previous_hash = models.CharField(max_length=64, blank=True)
    event_hash = models.CharField(max_length=64, editable=False, db_index=True)

    def save(self, *args, **kwargs):
        if not self.event_hash:
            canonical = json.dumps(
                {
                    "action": self.action,
                    "object_type": self.object_type,
                    "object_id": self.object_id,
                    "payload": self.payload,
                    "previous_hash": self.previous_hash,
                },
                sort_keys=True,
                default=str,
            )
            self.event_hash = hashlib.sha256(canonical.encode()).hexdigest()
        super().save(*args, **kwargs)
