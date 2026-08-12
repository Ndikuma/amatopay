# AmatoPay merchant webhooks

Create webhook destinations from **Merchant Dashboard → Developers**. The
`whsec_...` secret is displayed once after creation or rotation and must be
stored securely by the merchant.

AmatoPay sends compact JSON with these headers:

- `Content-Type: application/json`
- `X-AmatoPay-Event: evt_...`
- `AmatoPay-Signature: t=<unix_timestamp>,v1=<hmac_sha256>`

To verify a request, compute HMAC-SHA256 over the exact bytes
`<timestamp>.<raw_request_body>` using the endpoint secret. Compare the result
with `v1` using a constant-time comparison and reject stale timestamps. Process
events idempotently using the payload `id`.

Return any `2xx` status after persisting the event. Other responses and network
errors are retried with bounded exponential delays. AmatoPay stores an immutable
attempt history for operations monitoring. Staff can replay a non-delivered
event from Django Unfold without changing its event ID or payload.

Endpoint URLs must use HTTPS and cannot resolve to private, loopback, link-local,
or reserved network addresses.

Common events include:

- `payment.paid`
- `payment.failed`
- `settlement.completed`
