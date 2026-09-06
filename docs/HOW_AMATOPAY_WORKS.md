# How AmatoPay Works

AmatoPay is a merchant-first e-commerce payment gateway operated by Amato Tech. Merchants integrate once with AmatoPay. The underlying institution rail (currently CECF) is internal and is not part of the merchant-facing contract.

## Public merchant contract

A merchant creates a Checkout Session with the payer's MOBILE alias. AmatoPay verifies the alias, captures the resolved customer name and starts the collection internally. The optional alias-verification endpoint remains available for a name preview, but is not required for session creation.

### Checkout session

`POST /api/v1/checkout/sessions/`

```json
{
  "order_number": "ORDER-10082",
  "description": "Online purchase",
  "amount": "150000.00",
  "currency": "BIF",
  "payer_alias": "+25779000000",
  "return_url": "https://merchant.bi/payment/result",
  "metadata": {"invoice": "INV-10082"}
}
```

AmatoPay returns the hosted `checkout_url`, `client_secret`, resolved `payer_display_name`, server-calculated `expires_at`, AmatoPay `payment_reference`, and `payment_status`. Every session lives for three hours. An invalid or inactive alias creates no checkout or financial record.

## Browser return

After a terminal checkout outcome, AmatoPay redirects the browser to the same `return_url` with only the AmatoPay payment reference, for example:

`https://merchant.bi/payment/result?payment_reference=AMP-PAY-...`

The merchant must query AmatoPay for the authoritative status. The browser redirect is UX, not payment proof.

## Merchant webhook

The merchant configures one or more endpoints from **Dashboard → Developers**.

```json
{
  "url": "https://merchant.bi/api/amatopay/webhook",
  "events": ["payment.paid", "payment.failed", "settlement.completed"],
  "description": "Production payments"
}
```

AmatoPay shows a `whsec_...` signing secret once. Each webhook contains an `AmatoPay-Signature` header and a normalized AmatoPay event.

## Money flow

1. Merchant creates checkout.
2. Payer opens hosted AmatoPay checkout.
3. AmatoPay verifies the payer alias through the internal rail.
4. AmatoPay generates a six-digit secure release code. It stores a one-way password hash on the payment for verification and an authenticated-encrypted copy on the collection for future direct delivery to the payer. The readable code is not placed in API responses, audit payloads, logs, or merchant views.
5. AmatoPay sends the collection request whose creditor is the dedicated AmatoPay fiduciary/collection alias.
6. CECF handles payer authentication/approval and account debit.
7. AmatoPay polls the MobileCash transaction reference until the collection reaches a terminal state.
8. AmatoPay updates Payment, records fiduciary holding, and emits merchant webhook `payment.paid`.
9. Browser returns to merchant `return_url`.
10. After delivering the product or service, the merchant sends the public delivery link to the payer or submits the payer-provided six-digit code to `POST /api/v1/payments/{reference}/confirm-delivery/`.
11. A correct code confirms delivery and makes the held funds eligible for release. Five incorrect attempts lock verification.
12. AmatoPay creates the net settlement and sends P2P from the AmatoPay fiduciary alias to the merchant's verified receiver alias.
13. AmatoPay polls the MobileCash transaction reference for the P2P result.
14. AmatoPay completes Settlement/FundHold/Payment and emits `settlement.completed`.

### Confirm delivery with the payer's secure code

```http
POST /api/v1/payments/AMP-PAY-.../confirm-delivery/
X-Api-Key: sk_...
Content-Type: application/json

{
  "secure_code": "482731"
}
```

The payment reference is already part of the URL and must not be repeated in
the JSON body. No delivery evidence, tracking number, or merchant reference is
required by this endpoint.

The merchant must never receive this code from an AmatoPay API response. Only
the payer sees it in the institution's payment-request description and may provide it after
the merchant completes delivery or service.

The collection's encrypted copy is temporary and is erased after successful delivery
confirmation. Its encryption key is configured separately from the database
through `RELEASE_CODE_ENCRYPTION_KEYS`, allowing AmatoPay to add a direct payer
delivery channel without storing the code as plaintext.


## Private CECF integration

CECF exposes alias verification, collection, payout and transaction-reference status. It
does not call AmatoPay. AmatoPay polls status and then sends its own normalized,
signed merchant webhooks.

## Core AmatoPay domains

- Merchants: merchant account, KYB, beneficial owners, verified settlement accounts, team.
- Developers: test/live API keys, request authentication, API logs.
- Checkout: hosted Checkout Sessions and browser return handling.
- Payments: payment state machine and status history.
- Webhooks: merchant endpoints, signed events, retry delivery.
- Fiduciary: held funds and immutable ledger entries.
- Deliveries: delivery/service confirmation.
- Settlements: net payout calculation and merchant P2P.
- Deliveries/Protection claims: delivery confirmation, claims, evidence and resolution.
- Refunds: provider-backed reversal requests and their status.
- Compliance: merchant due diligence, suspicious activity and audit.
- CECF: collection/payout status recovery and provider reconciliation.
- Payments: payment state, immutable fee decisions and status history.
