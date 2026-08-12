import ipaddress
import socket
from urllib.parse import urlparse

from rest_framework.exceptions import ValidationError


def validate_webhook_url(url, *, resolve_dns=False):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValidationError("Webhook URLs must use HTTPS.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
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
                        hostname, parsed.port or 443, type=socket.SOCK_STREAM
                    )
                )
            except socket.gaierror as exc:
                raise ValidationError("Webhook host could not be resolved.") from exc
    if any(not address.is_global for address in addresses):
        raise ValidationError("Webhook URL cannot target a private or reserved address.")
    return url
