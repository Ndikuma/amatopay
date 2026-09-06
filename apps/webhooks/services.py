import hashlib, hmac, json, time
from datetime import timedelta
import requests
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import WebhookAttempt, WebhookEvent, WebhookDelivery
from .security import validate_webhook_url


def emit_event(merchant, event_type, data, object_type="", object_id=""):
    event = WebhookEvent.objects.create(
        merchant=merchant,
        type=event_type,
        payload={
            "id": None,
            "type": event_type,
            "created_at": timezone.now().isoformat(),
            "data": data,
        },
        object_type=object_type,
        object_id=str(object_id),
    )
    event.payload["id"] = event.event_id
    event.save(update_fields=["payload", "updated_at"])
    endpoints = merchant.webhook_endpoints.filter(active=True)
    for ep in endpoints:
        if not ep.events or event_type in ep.events or "*" in ep.events:
            WebhookDelivery.objects.get_or_create(event=event, endpoint=ep)
    return event


MAX_ATTEMPTS = 8
RETRY_DELAYS_SECONDS = (5, 30, 300, 1800, 3600, 7200, 14400)
RESPONSE_BODY_LIMIT = 8000


def _response_headers(response):
    """A plain, size-bounded dict of the merchant's response headers."""
    raw = getattr(response, "headers", None)
    if not raw:
        return {}
    try:
        return {str(k): str(v)[:1000] for k, v in dict(raw).items()}
    except Exception:
        return {}


@transaction.atomic
def deliver(delivery):
    delivery = WebhookDelivery.objects.select_for_update().select_related(
        "event", "endpoint"
    ).get(pk=delivery.pk)
    if delivery.status == WebhookDelivery.Status.DELIVERED:
        return delivery
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.next_retry_at = None
        delivery.save(update_fields=["status", "next_retry_at", "updated_at"])
        return delivery
    payload = json.dumps(
        delivery.event.payload, separators=(",", ":"), sort_keys=True
    ).encode()
    ts = str(int(time.time()))
    sig = hmac.new(
        delivery.endpoint.secret.encode(), ts.encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    started = time.monotonic()
    response_status = None
    response_body = ""
    response_headers = {}
    error = ""
    succeeded = False

    try:
        validate_webhook_url(delivery.endpoint.url, resolve_dns=True)
    except ValidationError as exc:
        # A URL that fails SSRF/scheme validation will never succeed — fail hard,
        # do not burn retry attempts on it.
        delivery.attempts += 1
        delivery.status = delivery.Status.FAILED
        delivery.last_error = str(getattr(exc, "detail", exc))[:4000]
        delivery.next_retry_at = None
        delivery.save()
        WebhookAttempt.objects.create(
            delivery=delivery,
            attempt_number=delivery.attempts,
            request_url=delivery.endpoint.url,
            request_headers={},
            request_body=delivery.event.payload,
            response_headers={},
            error=delivery.last_error,
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            succeeded=False,
        )
        return delivery

    try:
        r = requests.post(
            delivery.endpoint.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "AmatoPay-Signature": f"t={ts},v1={sig}",
                "X-AmatoPay-Event": delivery.event.event_id,
            },
            timeout=10,
        )
        response_status = r.status_code
        response_body = (r.text or "")[:RESPONSE_BODY_LIMIT]
        response_headers = _response_headers(r)
        delivery.attempts += 1
        delivery.last_status_code = r.status_code
        if 200 <= r.status_code < 300:
            delivery.status = delivery.Status.DELIVERED
            delivery.delivered_at = timezone.now()
            delivery.last_error = ""
            delivery.next_retry_at = None
            succeeded = True
        else:
            delivery.status = (
                delivery.Status.RETRYING
                if delivery.attempts < MAX_ATTEMPTS
                else delivery.Status.FAILED
            )
            delivery.last_error = f"HTTP {r.status_code}"
            delivery.next_retry_at = (
                timezone.now()
                + timedelta(
                    seconds=RETRY_DELAYS_SECONDS[
                        min(delivery.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)
                    ]
                )
                if delivery.attempts < MAX_ATTEMPTS
                else None
            )
    except Exception as exc:
        delivery.attempts += 1
        delivery.status = (
            delivery.Status.RETRYING
            if delivery.attempts < MAX_ATTEMPTS
            else delivery.Status.FAILED
        )
        error = str(exc)[:4000]
        delivery.last_error = error
        delivery.next_retry_at = (
            timezone.now()
            + timedelta(
                seconds=RETRY_DELAYS_SECONDS[
                    min(delivery.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)
                ]
            )
            if delivery.attempts < MAX_ATTEMPTS
            else None
        )
    delivery.last_response_body = response_body
    delivery.last_response_headers = response_headers
    delivery.save()
    WebhookAttempt.objects.create(
        delivery=delivery,
        attempt_number=delivery.attempts,
        request_url=delivery.endpoint.url,
        request_headers={
            "Content-Type": "application/json",
            "AmatoPay-Signature": f"t={ts},v1={sig}",
            "X-AmatoPay-Event": delivery.event.event_id,
        },
        request_body=delivery.event.payload,
        response_status=response_status,
        response_headers=response_headers,
        response_body=response_body,
        error=error,
        duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        succeeded=succeeded,
    )
    return delivery


def retry_now(delivery):
    if delivery.status == WebhookDelivery.Status.DELIVERED:
        return delivery
    delivery.status = WebhookDelivery.Status.PENDING
    delivery.next_retry_at = None
    delivery.save(update_fields=["status", "next_retry_at", "updated_at"])
    return deliver(delivery)


def deliver_pending(limit=100):
    qs = (
        WebhookDelivery.objects.select_related("event", "endpoint")
        .filter(status__in=["pending", "retrying"])
        .order_by("created_at")[:limit]
    )
    count = 0
    for d in qs:
        if d.next_retry_at and d.next_retry_at > timezone.now():
            continue
        deliver(d)
        count += 1
    return count
