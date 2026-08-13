import logging

from django.dispatch import receiver

from . import client
from .provider import MobileCashGatewayError
from .signals import rtp_created_with_release_code

logger = logging.getLogger(__name__)


@receiver(rtp_created_with_release_code)
def send_release_code_sms(sender, rtp, release_code, **kwargs):
    """Send the secure delivery code to the customer via SMS."""
    phone_number = rtp.payment.payer_alias
    message = f"Your AmatoPay secure delivery code is: {release_code}"
    try:
        client.send_sms(phone_number, message)
        logger.info("Sent delivery code SMS for RTP %s", rtp.request_id)
    except MobileCashGatewayError as exc:
        logger.error(
            "Failed to send delivery code SMS for RTP %s: %s", rtp.request_id, exc
        )