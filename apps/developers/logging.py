"""Safe serialization helpers for API request logs."""

import json
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_FIELDS = {
    "authorization",
    "client_secret",
    "password",
    "secret",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
}


def redact(value: Any) -> Any:
    """Recursively redact known credential fields from JSON-like data."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if str(key).lower() in SENSITIVE_FIELDS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def parse_json_body(body: bytes) -> dict[str, Any] | list[Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, (dict, list)):
        return {}
    return redact(parsed)
