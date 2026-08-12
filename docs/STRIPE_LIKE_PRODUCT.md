# Stripe-like AmatoPay product model

## Merchant-facing objects

- `Merchant` — business account
- `Merchant.owner` — direct authenticated merchant owner
- `MerchantApiKey` — test/live secret keys
- `MerchantWebhookEndpoint` — merchant callback configuration
- `PaymentSession` — hosted checkout session
- `Payment` — transaction object
- `Refund` — reversal/refund request
- `Settlement` — payout to merchant
- `WebhookEvent` — normalized merchant event
- `ApiRequestLog` — developer request log

## Public statuses

Payment: `created`, `processing`, `paid`, `failed`, `cancelled`, `refunded`, `settled`.
Internal states such as RTP and fiduciary release can remain visible in operations but do not need to leak provider-specific details to merchants.

## Webhook signature

`AmatoPay-Signature: t=<unix>,v1=<hmac-sha256>` computed over `<timestamp>.<raw-json-body>` using the endpoint secret.

Recommended events:
`payment.paid`, `payment.failed`, `payment.refunded`, `settlement.processing`, `settlement.completed`, `settlement.failed`, `dispute.opened`, `dispute.resolved`.
