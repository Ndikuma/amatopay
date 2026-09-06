import logging

from django.dispatch import receiver

from . import client
from .client import GatewayNotConfiguredError
from .provider import MobileCashGatewayError
from .signals import collection_created_with_release_code

logger = logging.getLogger(__name__)


@receiver(collection_created_with_release_code)
def send_release_code_sms(sender, collection, release_code, **kwargs):
    """Send the secure delivery code to the customer via SMS.

    Best-effort: a delivery-code SMS failure must never roll back the collection that
    was just persisted, so every error here is logged and swallowed.
    """
    phone_number = collection.payment.payer_alias
    message = f"Your AmatoPay secure delivery code is: {release_code}"
    try:
        client.send_sms(phone_number, message)
        logger.info("Sent delivery code SMS for collection %s", collection.request_id)
    except (MobileCashGatewayError, GatewayNotConfiguredError) as exc:
        logger.error(
            "Failed to send delivery code SMS for collection %s: %s", collection.request_id, exc
        )
    except Exception:
        logger.exception(
            "Unexpected error sending delivery code SMS for collection %s", collection.request_id
        )
