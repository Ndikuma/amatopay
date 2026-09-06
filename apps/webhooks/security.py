import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings
from rest_framework.exceptions import ValidationError


def _allow_insecure() -> bool:
    return bool(getattr(settings, "WEBHOOK_ALLOW_INSECURE_URLS", False))


def validate_webhook_url(url, *, resolve_dns=False):
    parsed = urlparse(url)
    insecure_ok = _allow_insecure()

    if not parsed.hostname or parsed.scheme not in ("https", "http"):
        raise ValidationError("Webhook URLs must use HTTPS.")
    if parsed.scheme != "https" and not insecure_ok:
        raise ValidationError("Webhook URLs must use HTTPS.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        if insecure_ok:
            return url
        raise ValidationError("Webhook URL must use a public host.")

    addresses = []
    try:
        addresses.append(ipaddress.ip_address(hostname))
    except ValueError:
        if resolve_dns:
            try:
                addresses.extend(
                    ipaddress.ip_address(item[4][0])
                    for item in socket.getaddrinfo(
                        hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                        type=socket.SOCK_STREAM,
                    )
                )
            except socket.gaierror as exc:
                raise ValidationError("Webhook host could not be resolved.") from exc
    if not insecure_ok and any(not address.is_global for address in addresses):
        raise ValidationError("Webhook URL cannot target a private or reserved address.")
    return url
