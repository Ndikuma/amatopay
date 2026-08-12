# AmatoPay API design principles

1. Merchant-facing resources use only AmatoPay terminology and AmatoPay references.
2. The underlying payment institution is an internal rail and is not a merchant API concept.
3. AmatoPay manages merchants, not retail customers.
4. The institution remains authoritative for payer KYC, authentication, account ownership, available funds and debit execution.
5. Every external money-moving request uses an immutable AmatoPay reference and must be idempotent.
6. RTP completion means the customer payment succeeded; it does not mean merchant settlement completed.
7. Merchant payout is allowed only from a release-pending hold and only to a verified primary settlement destination.
8. P2P completion, not request acceptance, finalizes settlement.
9. Original ledger entries are not edited to hide reversals or refunds; compensating entries are recorded.
10. Merchant webhooks should be signed and retryable.
