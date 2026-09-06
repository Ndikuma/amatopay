from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.webhooks.models import WebhookEvent
from apps.webhooks.services import emit_event

from .models import Refund


@receiver(post_save, sender=Refund)
def emit_refund_completed(sender, instance, **kwargs):
    """Notify the merchant once, when a refund reaches the completed state."""
    if instance.status != Refund.Status.COMPLETED:
        return
    already_sent = WebhookEvent.objects.filter(
        type="payment.refunded", object_type="refund", object_id=str(instance.pk)
    ).exists()
    if already_sent:
        return
    emit_event(
        instance.payment.merchant,
        "payment.refunded",
        {
            "payment_reference": instance.payment.reference,
            "refund_id": str(instance.pk),
            "amount": str(instance.amount),
            "reason": instance.reason,
            "currency": instance.payment.currency,
        },
        "refund",
        instance.pk,
    )
