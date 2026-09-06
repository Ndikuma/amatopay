# AmatoPay — Functionality Report

**Product:** AmatoPay — Merchant Payment Gateway (Amato Tech, Burundi)
**Prepared for:** Management review
**Scope:** Complete catalogue of implemented functionality, public interfaces, and operational tooling.

---

## 1. Executive summary

AmatoPay is a merchant payment gateway for the Burundian market. The product
boundary is deliberately close to Stripe: a business integrates **once** with
AmatoPay to accept mobile-money payments in BIF, while the underlying payment
institution ("the internal rail") stays hidden behind AmatoPay.

AmatoPay is responsible for **merchants** and **transaction-level payer
references** only. It does not hold retail customer accounts, balances, or
customer KYC — payer identity, authentication and account debit belong to the
payment institution.

What AmatoPay adds on top of the rail:

- A single, documented merchant API and hosted checkout.
- KYC/KYB-driven pricing with immutable fee snapshots per transaction.
- A fiduciary hold-and-release model so buyers are protected until delivery.
- Merchant settlement (payout) orchestration.
- Disputes, refunds, reconciliation and regulatory reporting.
- Signed webhooks with a retry queue.
- A full operations console for staff and a self-service dashboard for merchants.

### The money flow

```
Merchant server
   -> AmatoPay hosted checkout (session + client secret)
   -> payer alias verification
   -> collection request on the internal rail
   -> payment confirmed  (webhook: payment.paid)
   -> funds held in the fiduciary account
   -> delivery confirmed by the buyer's secure code (webhook: delivery.confirmed)
   -> hold released
   -> P2P payout to the merchant's settlement account (webhook: settlement.completed)
```

<<<PAGEBREAK>>>

## 2. Functionality catalogue

### 2.1 Merchant onboarding & KYB

- Public **merchant application** form (`/merchants/apply/`) — a six-step guided
  wizard collecting business identity, contact, statement descriptor, MCC,
  source of funds and KYB documents in one submission.
- Application creates, in one step: the Merchant record, a MerchantKYB record,
  the primary settlement account, and unverified document rows — leaving
  **review as the only remaining task**.
- **Staff review workflow**: `MerchantApplicationReview` records the decision;
  `MerchantKYB` tracks the verification decision (`pending`, `more_info`,
  `approved`, `rejected`).
- **KYB document vault** (`MerchantDocument`): registration, tax, licence,
  address, ID and bank documents, each independently verified.
- Merchant lifecycle status: `draft -> pending -> active -> suspended`.
- **Instant-settlement capability** — a per-merchant flag, granted after risk
  review, that lets a merchant skip the delivery-confirmation hold for services
  rendered immediately (transport tickets, airtime, event tickets).

### 2.2 Merchant workspace & team

- Every merchant has a workspace with a display name and a unique
  `merchant_code`.
- Team members and roles; staff can also open any workspace from the admin.
- **Merchant activity log** (`MerchantActivity`) — an audit trail of key
  actions (API key rotated, webhook toggled, secret rotated, test event queued).
- Self-service dashboard styled like a modern payments console
  (`/dashboard/`): overview, payments, settlements, refunds, trust &
  compliance, developers, business profile, billing.

### 2.3 API access & developer tooling

- **Rotatable API keys** (`sk_...`) — created, rotated and revoked from the
  dashboard; the plaintext secret is shown once.
- Authentication accepts `Authorization: Bearer sk_...` **or** `X-Api-Key:`.
- **Auth vs. authorization split**: the key only proves *who* the merchant is;
  a separate `IsActiveMerchant` permission enforces "merchant must be active"
  on every money-moving endpoint. Onboarding/status endpoints only need a valid
  key.
- **Idempotency** — every write request carries an `Idempotency-Key`;
  `IdempotencyKey` / `IdempotencyRecord` store and replay the first response so
  retries never double-charge.
- **Traceable request IDs** and structured request logging for support.
- **OpenAPI schema** published at `/api/schema/`, with Swagger UI (`/api/docs/`)
  and ReDoc (`/api/redoc/`); internal endpoints are filtered out of the schema.
- **Developer documentation** at `/developers/` — quickstart, authentication,
  ping & readiness, payment lifecycle, webhooks, and the security model.

### 2.4 Hosted checkout

- `POST /api/v1/checkout/sessions/` creates a **PaymentSession** with a
  `session_id` and a `client_secret`; the response is immediate — the gateway
  is not called synchronously.
- AmatoPay-hosted payment page at `/pay/<session_id>/` — the merchant redirects
  the payer there.
- **Alias verification** — the payer's mobile-money alias is checked before a
  payment is created, and the verified customer name is shown.
- One shared **return URL** for every outcome; merchants are told never to
  trust browser query parameters as proof of payment.
- **Status polling** — `GET /api/v1/checkout/sessions/<id>/status/` (client
  secret, no API key) so a merchant page can poll the outcome.
- `require_delivery_confirmation: false` is accepted from instant-settlement
  merchants to pay out immediately on `payment.paid`.

### 2.5 Payment processing & lifecycle

- **Payment** is the central financial record, with an 18-state lifecycle from
  `created` through `paid`, `funds_held`, `delivery_pending`, `release_pending`,
  `settlement_processing`, `settled` — plus the terminal failure states
  (`failed`, `rejected`, `cancelled`, `reversed`, `refunded`, `expired`,
  `fraud_blocked`).
- **PaymentStatusHistory** — every transition is recorded with its trigger.
- **Asynchronous collection**: checkout records the payment at `alias_verified`
  and returns; `process_pending_payments` submits the collection to the rail
  out-of-band; `reconcile_gateway` polls it to a terminal state.
- Merchant read API: `GET /api/v1/payments/` and
  `GET /api/v1/payments/{reference}/`.
- `POST /api/v1/payments/{reference}/confirm-delivery/` — confirm delivery with
  the buyer's secure code via the API.

<<<PAGEBREAK>>>

### 2.6 Pricing, fees & billing

- **Pricing plans** (`PricingPlan`) — pay-as-you-go percentage pricing and
  fixed-fee subscription plans with an included monthly transaction allowance.
- **Plan assignment** (`MerchantPlanAssignment`) — the active plan per merchant
  and currency, with controlled per-merchant overrides.
- **Plan requests** (`PlanRequest`) — a merchant requests a plan change from the
  dashboard; activation is paid through the normal collection flow.
- **Fee resolution** (`resolve_transaction_fee`) — chooses the plan, computes
  the fee, and records **why**.
- **Immutable fee snapshots** (`TransactionFee`) — the fee that applied to a
  transaction is frozen at capture time and can never be edited (enforced at
  the query-set level).
- **Fee quote API** — `POST /api/v1/fees/quote/` returns the fee breakdown for
  an amount before the merchant commits.

### 2.7 Protected funds (fiduciary)

- A single **FiduciaryAccount**, synchronised from the rail and verified via
  alias verification (`sync_fiduciary_account`).
- **FundHold** — one hold per protected payment, with its own state machine
  (`held`, `delivery_pending`, `delivery_confirmed`, `disputed`,
  `release_pending`, `refund_pending`, `frozen`, `released`, `refunded`).
- **FiduciaryEntry** — a double-entry style ledger of every movement in and out
  of the fiduciary account, for audit and reconciliation.
- Protection windows: **4 business days** for domestic transactions,
  **14 calendar days** for international, subject to compliance review.

### 2.8 Delivery confirmation & buyer protection

- On payment, the buyer receives a **six-digit secure code**.
- **Delivery** and **DeliveryConfirmation** records track fulfilment; the buyer
  releases funds by confirming with the secure code.
- Confirmation methods include the customer portal, the merchant API, and
  `instant_settlement` for services rendered on payment.
- **Public customer delivery portal** (`/deliveries/`) — a buyer looks up their
  order and either confirms receipt or reports a problem, with a
  progressive-disclosure decision form and protection-timeline outcome pages.
- The "I received my order" option is disabled with an explanation if the
  merchant cannot yet be paid; "report a problem" always stays available.

### 2.9 Disputes / protection claims

- **ProtectionClaim** — a formal case opened when a buyer reports a problem;
  funds are frozen (`payment.disputed` webhook).
- **ProtectionClaimEvidence** — files and statements from both sides.
- **ProtectionClaimEvent** — the case timeline.
- Outcomes: `won_customer`, `won_merchant`, `closed`.
- Staff manage claims from the operations console; merchants see their own
  claims in the dashboard.

### 2.10 Refunds

- **Refund** — full or partial, requested by staff or via signal from an
  upstream event.
- Refund lifecycle drives a `payment.refunded` webhook and a matching fiduciary
  entry; the payment moves to `refunded`.

### 2.11 Merchant settlement (payouts)

- **MerchantSettlementAccount** — the merchant's verified mobile-money number(s)
  where net funds are paid.
- **Settlement** and **SettlementBatch** — payout records; once a hold is
  released, `start_merchant_payout` creates a P2P payout request on the rail.
- `reconcile_gateway` polls payouts to completion and emits
  `settlement.completed` / `settlement.failed`.
- Merchants review settlements in the dashboard (there is no settlement write
  API — payouts are system-driven).

<<<PAGEBREAK>>>

### 2.12 Internal gateway rail & reconciliation

- **GatewayConfig** — the active rail configuration (endpoints, creditor alias,
  credentials), stored in the database and activated by staff.
- **AliasVerification** — cached payer/creditor alias checks.
- **GatewayRequest** — one unified model for both rails, tagged by `rail`:
  - `COLLECTION` — pulling funds from the payer.
  - `P2P` — paying out to the merchant.
- **GatewayCallback** — inbound notifications from the rail.
- **GatewayTransactionPoll** — the reconciliation poller's state per request.
- `reconcile_gateway` — polls every in-flight collection and payout, applies
  status transitions, respects rate limits, and starts pending payouts.
- A start-up **system check** warns if no active gateway configuration exists.

### 2.13 Webhooks

- **Signed** — every request carries
  `AmatoPay-Signature: t=<timestamp>,v1=<hex>` where `v1` is
  `HMAC-SHA256(endpoint_secret, "<timestamp>." + raw_body)`.
- **Retry queue** — failed deliveries retry with exponential backoff for up to
  **8 attempts**; a URL that fails SSRF/scheme validation fails hard instead of
  burning retries.
- **SSRF guard** — merchant webhook URLs must be HTTPS and public
  (a development override exists for local integration testing only).
- **Full audit trail**:
  - `WebhookEvent` — the event and its payload.
  - `WebhookDelivery` — status per endpoint, attempt count, last HTTP code,
    **and the last response body + headers the merchant returned**.
  - `WebhookAttempt` — an immutable record of every attempt with the request
    and the merchant's response.
- **Merchant self-service** — add/verify endpoints, choose event types, send a
  test event, rotate the signing secret, and inspect delivery status and the
  exact response their endpoint returned, all from `/dashboard/developers/`.
- **Event catalogue** (`apps/webhooks/events.py`) is the single source of truth
  and is surfaced in the dashboard.

### 2.14 Compliance & regulatory reporting

- **SuspiciousTransaction** — suspicious activity reports, with status tracking
  and flags for BRB / CNRF reporting.
- **RegulatoryReport** — admin-frozen report snapshots; once generated, the
  data is captured and immutable.
- **DataRetentionRecord** — the data-retention schedule.
- **Report registry** (`apps/compliance/reports.py`) with **seven built-in
  reports**: Transactions, Settlements, Fee income, Protected funds, Suspicious
  activity, Merchant onboarding, Data retention.
- **Exports** — every report renders to **CSV** and **PDF** (`exports.py`), and
  any admin change-list selection can be exported the same way.

### 2.15 Security

- API-key authentication with an auth / authorization split.
- Idempotency and request-ID tracing on every write.
- Webhook signing and SSRF protection.
- Encrypted storage for provider secret keys and release codes
  (application-level field encryption).
- **Security centre** (`/security/`) — a dedicated console for security alerts,
  blocked IPs, and a request log, with live statistics.
- Production security is enforced by tests
  (`config/tests/test_production_security.py`) that assert the non-public API
  surface stays 404.
- Deployment hardening: HTTPS redirect, HSTS, secure cookies, content-type
  nosniff, `X-Frame-Options: DENY`, referrer policy — all gated on `DEBUG=0`.

### 2.16 Operations console (staff admin)

- Django Unfold admin themed as **"AmatoPay Operations"** with a custom
  dashboard: payments today, funds protected, pending settlement, fees today,
  a 14-day volume chart, payment-status breakdown, an operations queue and
  recent activity.
- Grouped sidebar with **live badges** (pending payments, protected funds,
  open claims, KYB reviews, merchant applications, gateway state, compliance
  attention, webhook failures, security alerts).
- Every operational and financial model has an admin; immutable records are
  presented read-only.
- Rail-filtered links to collections and payouts from the unified changelist.

### 2.17 Platform operations

- **Single worker process** — `manage.py run_workers` runs every background job
  (`process_pending_payments`, `reconcile_gateway`, `process_webhooks`) on its
  own interval in its own thread, with per-job failure isolation and a clean
  `SIGTERM` shutdown. Jobs are configured in settings; a systemd unit ships in
  `deploy/`.
- **Health endpoints** — `/health/live/` and `/health/ready/`.
- **Seed / bootstrap commands** — `bootstrap_merchant`, `seed_pricing_plans`,
  `seed_demo_merchants`, `seed_data`.
- All runtime configuration (rail credentials, provider secrets) lives in the
  database and is editable by staff — no redeploy to rotate a key.

<<<PAGEBREAK>>>

## 3. Public API surface

Only these endpoints are exposed to merchants. Everything else is staff-only or
system-driven.

| Method | Endpoint | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/ping/` | Key check + merchant readiness + pending steps | API key |
| POST | `/api/v1/checkout/alias-verifications/` | Verify a payer alias | Active merchant |
| POST | `/api/v1/checkout/sessions/` | Create a hosted-checkout session | Active merchant |
| GET | `/api/v1/checkout/sessions/{id}/status/` | Poll checkout outcome | Client secret |
| GET | `/api/v1/payments/` | List payments | Active merchant |
| GET | `/api/v1/payments/{reference}/` | Payment detail | Active merchant |
| POST | `/api/v1/payments/{reference}/confirm-delivery/` | Confirm delivery by secure code | Active merchant |
| POST | `/api/v1/fees/quote/` | Fee breakdown for an amount | Active merchant |
| GET | `/api/schema/`, `/api/docs/`, `/api/redoc/` | OpenAPI schema and explorers | Public |
| GET | `/health/live/`, `/health/ready/` | Liveness / readiness | Public |

## 4. Webhook event catalogue

| Event | Meaning |
|---|---|
| `payment.processing` | Payer approved the request; collection is in progress. |
| `payment.awaiting_approval` | The collection is waiting for the payer to approve it. |
| `payment.paid` | Funds were collected and are now protected. |
| `payment.failed` | The payment was rejected, failed, or cancelled. |
| `delivery.confirmed` | The customer confirmed delivery with their secure code. |
| `payment.disputed` | The customer opened a delivery investigation; funds are frozen. |
| `settlement.completed` | Net funds were released and paid to the merchant. |
| `settlement.failed` | A merchant payout attempt failed. |
| `payment.refunded` | A refund on the payment completed. |

## 5. Data model summary

| Domain | Models |
|---|---|
| Checkout | PaymentSession |
| Payments | Payment, PaymentStatusHistory, TransactionFee, IdempotencyRecord |
| Billing | PricingPlan, MerchantPlanAssignment, PlanRequest |
| Gateway (rail) | GatewayConfig, AliasVerification, GatewayRequest, GatewayCallback, GatewayTransactionPoll |
| Merchants | MerchantApplication, MerchantApplicationReview, Merchant, MerchantKYB, MerchantDocument, MerchantSettlementAccount, MerchantApiKey, MerchantWebhookEndpoint, MerchantActivity |
| Fiduciary | FiduciaryAccount, FundHold, FiduciaryEntry |
| Deliveries | Delivery, DeliveryConfirmation, ProtectionClaim, ProtectionClaimEvidence, ProtectionClaimEvent |
| Settlements | SettlementBatch, Settlement |
| Refunds | Refund |
| Compliance | SuspiciousTransaction, RegulatoryReport, DataRetentionRecord |
| Webhooks | WebhookEvent, WebhookDelivery, WebhookAttempt |
| Developers | IdempotencyKey |
| Core | AuditEvent |

## 6. Integrations

- **Amato Travel Connect** — a sibling bus-ticketing platform consumes AmatoPay
  as its payment gateway. Each transport operator is a separate AmatoPay
  merchant; TravelConnect uses instant settlement for tickets. This validates
  the gateway against a real third-party integration.

## 7. Operational maturity

The application is a **complete, working foundation**. Before a live regulated
launch, the following external gates remain (tracked in
`docs/PRODUCTION_READINESS.md`): mutual-TLS to the rail, HSM/KMS key management,
production PostgreSQL, object storage for documents, a sanctions/PEP screening
provider, WORM audit retention, monitoring/SIEM, disaster-recovery drills,
penetration testing, and regulator-approved report formats.

## 8. Appendix

### Management commands

| Command | Purpose |
|---|---|
| `run_workers` | Run all background jobs in one process |
| `process_pending_payments` | Submit collections for async checkout payments |
| `reconcile_gateway` | Poll collections and payouts to a terminal state |
| `process_webhooks` | Deliver queued merchant webhooks |
| `sync_fiduciary_account` | Verify and sync the fiduciary account from the rail |
| `bootstrap_merchant` | Create a merchant for testing / onboarding |
| `seed_pricing_plans` | Load the standard pricing plans |
| `seed_demo_merchants` | Load demo merchants |
| `seed_data` | Load baseline reference data |
| `functionality_report` | Render this document to a branded PDF |

### Payment lifecycle states

`created` -> `alias_verified` -> `collection_pending` -> `awaiting_approval` ->
`processing` -> `paid` -> `funds_held` -> `delivery_pending` ->
`release_pending` -> `settlement_processing` -> `settled`.

Off-path states: `disputed`, `failed`, `rejected`, `cancelled`, `reversed`,
`refunded`, `expired`, `fraud_blocked`.
