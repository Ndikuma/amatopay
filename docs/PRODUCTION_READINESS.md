# AmatoPay production readiness

This is the release gate for an environment that processes real funds. Passing
application tests is necessary, but does not replace the external controls below.

## Implemented application controls

- Central, effective-dated KYC/KYB pay-as-you-go fees and contracted merchant plans.
- Immutable transaction fee snapshots; settlements consume stored net amounts.
- Database constraints on payment, session, fee, fiduciary, refund, and settlement amounts.
- Staff-only operations APIs and merchant-scoped financial APIs.
- No public action can locally complete a payout or refund.
- Checkout secrets appear only in the create response; expired, cancelled, and duplicate payment starts are rejected.
- Delivery release requires the payer's six-digit confirmation code.
- HTTPS-only webhooks reject local/private/reserved destinations, including after DNS resolution.
- Health/readiness checks, structured logging, secure cookies, HSTS, non-root containers, proxy and worker configuration.
- Compliance uploads are not exposed through the public Nginx proxy.

## Required before live payments

These are infrastructure, provider, finance, or compliance dependencies and cannot
safely be invented in source code.

1. Put unique application and database secrets in a managed secret store; configure production hosts and trusted origins.
2. Create, test, and activate the real provider record in **Admin → Payment gateway**. `gateway.W001` intentionally remains until the database configuration is active.
3. Terminate TLS, enable HTTPS redirect/HSTS, and use `POSTGRES_SSLMODE=require` where the database supports TLS.
4. Use private object storage or authenticated downloads for KYC/KYB and dispute evidence. Never add a public `/media/` alias.
5. Move gateway passwords and webhook signing secrets to encrypted secret storage with a rotation procedure.
6. Complete provider-certified refund/reversal integration. Refund requests are recorded, but the unsafe local completion route was removed.
7. Validate ledger mappings and reconciliation with provider sandbox transactions, including retries and failures.
8. Obtain compliance approval for required documents, expiry, limits, sanctions, disputes, and retention.
9. Configure backups and restore tests, monitoring, alerting, centralized logs, worker supervision, and incident response.
10. Complete penetration testing and a controlled production smoke test before raising live limits.

## Release verification

```bash
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py test
```

`/health/live/` checks the process and `/health/ready/` checks database access. Do
not route traffic to an instance until readiness succeeds.

Current baseline on 2026-08-09: all migrations applied, 51 tests pass, and the
deployment check has no Django security warning. Its sole warning is the expected
missing live gateway configuration. A local pre-migration backup is at
`/tmp/amatopay-pre-production-audit.sqlite3`; move it into normal backup storage if
it must be retained.
