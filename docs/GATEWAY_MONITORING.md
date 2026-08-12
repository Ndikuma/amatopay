# Gateway transaction monitoring

RTP collections and P2P payouts are monitored with the institution `trxRef` returned when the transaction is created. AmatoPay persists that value and calls `TRANSACTION_BY_REFERENCE` until the gateway reports a terminal status.

The dedicated worker runs:

```bash
python manage.py reconcile_gateway --watch --interval 20
```

It is already configured as the `gateway-worker` service in Docker Compose. Do not start a scheduler inside Django web workers; doing so would duplicate polling when Gunicorn has multiple processes.

Monitoring behavior:

- pending RTP and P2P records are selected only when `next_poll_at` is due;
- successful polls reset the failure counter and schedule the next normal poll;
- timeouts, 404s and gateway failures use bounded exponential backoff;
- HTTP 429 stops the current cycle early to avoid amplifying rate limiting;
- every poll writes an immutable `GatewayTransactionPoll` audit record;
- terminal status application remains idempotent through callback event identifiers;
- transaction references are unique per rail and mismatched references are rejected.

Operators can inspect poll history in **Unfold → Gateway → Transaction monitoring**.
