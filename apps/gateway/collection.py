"""Shared collection payment-rail primitives used by checkout and billing workflows."""

import re
import uuid

from django.db import transaction

from . import client
from .models import GatewayRequest
from .signals import collection_created_with_release_code
from .release_codes import encrypt_release_code


class PaymentGatewayError(RuntimeError):
    """Raised when the payment rail fails; hides raw gateway details from callers."""


_RELEASE_CODE_PATTERN = re.compile(
    r"(AmatoPay release code:\s*)\d{6}", re.IGNORECASE
)


def redact_release_code(value):
    """Remove the payer-only release code from persisted gateway audit data."""
    if isinstance(value, dict):
        return {key: redact_release_code(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_release_code(item) for item in value]
    if isinstance(value, str):
        return _RELEASE_CODE_PATTERN.sub(r"\1[REDACTED]", value)
    return value


def new_collection_request_id(*, prefix="AMP-COLL") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def call_create_collection(payload: dict) -> dict:
    """Submit a collection to MobileCash and return the provider response."""
    from .provider import MobileCashGatewayError

    try:
        result = client.create_collection(payload)
    except MobileCashGatewayError as exc:
        raise PaymentGatewayError(
            "Payment could not be initiated. Please try again."
        ) from exc
    provider_ref = result.get("trxRef") or result.get("providerReference", "")
    if not provider_ref:
        raise PaymentGatewayError("Payment could not be initiated. Please try again.")
    return result


@transaction.atomic
def persist_collection_request(
    *,
    request_id: str,
    payload: dict,
    result: dict,
    payment=None,
    plan_request=None,
    release_code: str | None = None,
) -> GatewayRequest:
    """Persist an collection GatewayRequest linked to its owning checkout or billing object."""
    collection_kwargs = {
        "rail": GatewayRequest.Rail.COLLECTION,
        "request_id": request_id,
        "provider_reference": result.get("trxRef") or result.get("providerReference", ""),
        "status": result.get("status", "PENDING").lower(),
        "raw_request": redact_release_code(payload),
        "raw_response": redact_release_code(result),
    }
    if payment is not None:
        collection_kwargs["payment"] = payment
    if plan_request is not None:
        collection_kwargs["plan_request"] = plan_request
    if release_code:
        collection_kwargs["release_code_ciphertext"] = encrypt_release_code(release_code)

    collection = GatewayRequest.objects.create(**collection_kwargs)
    if release_code and collection.payment:
        collection_created_with_release_code.send(
            sender=GatewayRequest, collection=collection, release_code=release_code
        )
    return collection
