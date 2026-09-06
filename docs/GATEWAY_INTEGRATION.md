# BurundiPay / CECF gateway integration

AmatoPay keeps the merchant API independent from the underlying payment rail.
The internal rail uses the supplied BurundiPay/MobileCash gateway contract.

| Provider | Authentication | Collection | Settlement |
| --- | --- | --- | --- |
| BurundiPay/MobileCash | Username/password → cached JWT | Alias, collection, transaction polling | P2P to verified merchant alias |

## Database configuration

Use **Admin → Payment gateway → Gateway configurations**. Create one
BurundiPay/MobileCash record, enter its authentication details, test the
connection from the admin action, and activate it. Only one gateway can be
active. Editing a gateway with password/secret fields left blank preserves the
saved values and the admin never renders those values back into the browser.

The database record is the only configuration source; there is no settings or
environment fallback. Restrict Django admin and database access because these
credentials are operational secrets. For deployments requiring KMS/HSM-backed
encryption, integrate field-level encryption before entering live credentials.

The `creditor_alias` field is the verified AmatoPay fiduciary/collection alias. It
receives every customer collection and is also the payer alias for released
merchant P2P settlements. It must identify the dedicated account used for
e-commerce funds, not an AmatoPay operating account. Credentials stay server-side and the JWT is cached until just
before expiry. A `401` invalidates the cached token and causes one authenticated
retry.

The gateway uses only the supplied MobileCash endpoints:

- `POST /api/external/login`
- `POST /api/alias/verify`
- `POST /api/MobileTrxPay/rtp`
- `POST /api/MobileTrxPay/p2p`
- `GET /api/MobileTrxPay/reference/{reference}`

No client ID, request HMAC, callback URL or QR endpoint is used. MobileCash
response shapes and statuses are normalized into AmatoPay's internal
`found/status/customer/account` and `providerReference/status` contracts.

## Status reconciliation

Completion is discovered by polling the transaction reference rather than by
receiving a callback. Run this command on a scheduler:

```bash
python manage.py reconcile_gateway --limit 100
```

Or run the included long-lived worker (also configured in `docker-compose.yml`):

```bash
python manage.py reconcile_gateway --watch --interval 20
```

Recovered transitions use deterministic
event IDs, so repeated polling is idempotent. Completion then follows AmatoPay's
normal flow: payment history, fiduciary hold, checkout completion, and merchant
webhook creation.

## MobileCash settlement contract

After delivery confirmation (or another valid release decision), AmatoPay
creates a settlement and calls `POST /api/MobileTrxPay/p2p` with only:

```json
{
  "payerAlias": "AMATOPAY_FIDUCIARY_ALIAS",
  "receiverAlias": "VERIFIED_MERCHANT_ALIAS",
  "amount": 95000,
  "description": "AmatoPay merchant settlement AMP-STL-..."
}
```

The amount is the merchant net settlement amount. P2P status is reconciled
through the shared transaction-reference lookup. Only a completed P2P marks the
fund hold released and the payment settled.

The two aliases have distinct roles and must never be equal:

- `payerAlias` is always the active AmatoPay fiduciary/collection alias from the gateway configuration.
- `receiverAlias` is always the merchant's active, verified, primary MOBILE settlement alias for the payment currency.

Delivery confirmation is rejected until an eligible merchant settlement alias
exists. This prevents consuming the customer's secure code when AmatoPay cannot
route the released funds to the merchant.
