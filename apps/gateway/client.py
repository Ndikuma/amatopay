"""Database-configured MobileCash gateway facade."""

from .provider import MobileCashGateway
from .models import GatewayConfig

_mobilecash_client = None
_mobilecash_cache_key = None


class GatewayNotConfiguredError(RuntimeError):
    pass


def _configuration():
    """Return the single active database configuration."""
    configured = GatewayConfig.active()
    if not configured:
        raise GatewayNotConfiguredError(
            "No active payment gateway is configured. Configure and activate one in Django Admin."
        )
    return configured


def _mobilecash() -> MobileCashGateway:
    global _mobilecash_client, _mobilecash_cache_key
    config = _configuration()
    cache_key = (config.pk, config.updated_at)
    if _mobilecash_client is None or _mobilecash_cache_key != cache_key:
        _mobilecash_client = MobileCashGateway(
            base_url=config.base_url,
            username=config.username,
            password=config.password,
            creditor_alias=config.creditor_alias,
            timeout=config.timeout_seconds,
            verify_tls=config.verify_tls,
        )
        _mobilecash_cache_key = cache_key
    return _mobilecash_client


def verify_alias(payload):
    result = _mobilecash().verify_alias(
        payload["alias"], payload.get("aliasType", "MOBILE")
    )
    result["requestId"] = payload["requestId"]
    return result


def create_rtp(payload):
    return _mobilecash().create_rtp(payload)


def get_rtp_status(reference):
    return _mobilecash().get_transaction(reference)


def create_p2p(payload):
    return _mobilecash().create_p2p(payload)


def get_p2p_status(reference):
    return _mobilecash().get_transaction(reference)


def send_sms(phone_number, message):
    return _mobilecash().send_sms(phone_number, message)
