# AmatoPay — Merchant Payment Gateway

Before enabling live payments, complete every external release gate in
[Production readiness](docs/PRODUCTION_READINESS.md).

**Functionality report:** [`docs/AMATOPAY_FUNCTIONALITY.md`](docs/AMATOPAY_FUNCTIONALITY.md)
is the full catalogue of implemented features, public interfaces and operational
tooling. Render it to a branded PDF for review with:

```bash
python manage.py functionality_report          # -> build/AmatoPay-Functionality-Report.pdf
```

AmatoPay is an Amato Tech merchant payment gateway for Burundi. The product boundary is deliberately similar to Stripe: merchants integrate once with AmatoPay, while the underlying institution rail stays internal.

## Product surface

- Merchant onboarding + KYB + beneficial owners
- Team workspaces and roles
- Rotatable merchant API keys (`sk_...`)
- Hosted checkout sessions + client secrets
- KYC/KYB-based transaction fees, controlled merchant overrides, and immutable fee snapshots
- Payment links
- Merchant payment API and request logs
- Alias verification + collection through internal rail
- Fiduciary hold / delivery / release workflow
- Merchant settlement through P2P
- Protection claims, refunds, gateway reconciliation, and compliance
- Signed merchant webhooks with retry queue
- Stripe-like merchant dashboard
- Idempotency model and traceable API request IDs

## Money flow

Merchant -> AmatoPay Checkout -> alias verify -> collection -> payment confirmed -> fiduciary hold -> delivery confirmation -> release -> P2P merchant settlement -> merchant webhook.

AmatoPay does not manage retail customer accounts/KYC. The payment institution owns payer identity, customer authentication, balance and account debit. AmatoPay manages merchants and transaction-level payer references only.

## Quick start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Build the Tailwind stylesheet in another terminal:

```bash
npm install
npm run css:watch
```

Use `npm run css:build` for a minified production stylesheet.

The default configuration uses SQLite for local development. To run with
PostgreSQL, populate the `POSTGRES_*` variables in `.env`. Production must use
`DEBUG=0`, a strong `SECRET_KEY`, explicit hosts/origins, HTTPS, and non-default
provider credentials in the database through Django Admin.

Validate a deployment configuration with:

```bash
python manage.py check --deploy
python manage.py test
```

Create a demo merchant:

```bash
python manage.py bootstrap_merchant --name "Amato Shop" --email merchant@example.bi --code AMP-MER-000001
```

## Merchant API example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/checkout/sessions/ \
  -H "Authorization: Bearer sk_..." \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-1001" \
  -d '{
    "order_number":"ORDER-1001",
    "description":"Online purchase",
    "amount":"50000.00",
    "currency":"BIF",
    "payer_alias":"+25779000000",
    "return_url":"https://merchant.bi/payment/result"
  }'
```

## Internal rail contract

CECF/internal institution exposes only:

- `POST /api/v1/checkout/sessions/` — verify payer alias, create checkout and initiate the collection
- `POST /api/amatopay/v1/rtp`
- `GET /api/amatopay/v1/rtp/{reference}`
- `POST /api/amatopay/v1/p2p`
- `GET /api/amatopay/v1/p2p/{reference}`

AmatoPay polls the institution's transaction-reference endpoint for collection and payout
completion, then sends normalized signed webhooks to merchants.

## Background workers

All periodic jobs run in **one** process:

```bash
python manage.py run_workers            # runs every job in settings.AMATOPAY_WORKERS
python manage.py run_workers --list     # show configured jobs + intervals
python manage.py run_workers --once     # single pass of each job, then exit
python manage.py run_workers --only reconcile_gateway,process_webhooks
```

It runs each management command (`process_pending_payments`, `reconcile_gateway`,
`process_webhooks`) on its own interval in its own thread; one job failing never
stops the others, and `SIGTERM` drains cleanly. Add or retune jobs in
`settings.AMATOPAY_WORKERS` — no code change needed.

Deploy as a single unit: `deploy/amatopay-workers.service` (copy to
`/etc/systemd/system/`, adjust paths/user, `systemctl enable --now amatopay-workers`).

## Production note

This repository is a complete application foundation, not a claim of regulatory or infrastructure certification. Before live regulated deployment, complete mTLS, HSM/KMS key management, PostgreSQL production configuration, async workers/queues, object storage, sanctions/PEP provider integration, immutable/WORM audit retention, monitoring/SIEM, disaster recovery, penetration testing, and regulator-approved reporting formats.


## Return URL vs merchant webhook

AmatoPay uses one browser `return_url` for all checkout outcomes. The merchant must not trust browser query parameters as payment proof; it should query `GET /api/v1/payments/{reference}/` or rely on a signed webhook.

Merchant webhooks are configured from **Dashboard → Developers**. AmatoPay sends signed server-to-server events such as `payment.paid`, `payment.failed`, and `settlement.completed`.

CECF never calls the merchant directly. AmatoPay polls collection/payout results and emits its own normalized merchant webhook.
