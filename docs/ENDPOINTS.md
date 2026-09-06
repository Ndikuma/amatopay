# AmatoPay endpoint map

Only merchant integration endpoints are exposed. Merchant/KYB administration,
gateway operations, compliance, fiduciary accounting and settlement batches are
managed through Django Unfold and have no `/api/v1/` routes.

## Checkout and collection

- `GET /api/v1/fees/quote/?amount=100000&currency=BIF` (KYC/KYB fee quote)
- `GET /api/v1/checkout/alias-verifications/?payer_alias=%2B25779000000` (optional MOBILE alias/name lookup)
- `GET /api/v1/checkout/sessions/{id}/`
- `POST /api/v1/checkout/sessions/` (merchant API key; accepts `payer_alias`, verifies it and initiates the collection)

The merchant supplies only the payer's MOBILE alias when creating a session. AmatoPay verifies it and records the resolved payer name before creating the session, payment and collection. Session expiry is fixed by AmatoPay at three hours. The hosted
checkout only shows the already-created payment request and polls its status.
The six-digit release code is visible only to the payer in the payment-request description
and is never returned to the merchant API.

**Instant settlement.** Merchants granted the `instant_settlement_enabled` capability
may create a session with `"require_delivery_confirmation": false`. Those payments
carry no secure code and no delivery-confirmation hold: on collection they auto-confirm
(`delivery.confirmed`, method `instant_settlement`) and the payout to the merchant
starts immediately. Use it for services rendered on payment (transport tickets, airtime,
event tickets, digital goods). A `POST` with the flag from a merchant without the
capability is rejected `400`.

## Payment lifecycle

- `GET /api/v1/payments/`
- `GET /api/v1/payments/{id}/`
- `POST /api/v1/payments/{reference}/confirm-delivery/` (merchant API key + payer's six-digit secure code)
- `POST /api/v1/payments/{reference}/delivery-review/` (merchant API key + payer alias or code + alternative proof metadata; opens review only)
- `GET|POST /deliveries/{payment-reference}/` (public payer delivery decision)

The public delivery page lets the payer either confirm receipt or report a
missing, incomplete, damaged, or misdescribed product/service using the
six-digit delivery code. Confirmation releases the protected funds. A report
invalidates that code, freezes the funds, marks the payment disputed, and opens
an auditable AmatoPay investigation. The merchant payment API returns the
`delivery_decision_url` that can be sent to the customer.

If the delivery code did not reach the payer, the payer can verify with the
original payment alias and submit a receipt, photo, delivery note, or service
acceptance document. This alternative evidence opens a manual verification
case and freezes funds; it never releases funds automatically. This separation
prevents a merchant-controlled tracking number or document from being used to
self-approve settlement.

Refunds remain visible in the authenticated merchant dashboard but are managed
by AmatoPay Operations. Protection-claim investigation and evidence management
remain internal operations workflows.

## Settlement

- `GET /api/v1/settlements/items/`
- `GET /api/v1/settlements/items/{id}/`

Payout initiation is internal. AmatoPay automatically uses the merchant's verified, active, primary MOBILE settlement alias after delivery confirmation.

## Webhooks

Webhook destinations are configured through **Merchant Dashboard → Developers**,
not through the API. See `docs/WEBHOOKS.md` for signature verification, retries
and replay behavior.
