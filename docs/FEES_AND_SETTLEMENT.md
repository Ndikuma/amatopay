# KYC/KYB fees and settlement

AmatoPay uses one fee engine for contracted pricing plans and verification-based
pay-as-you-go fees. Each decision is snapshotted so later pricing
changes never rewrite historical transactions.

## Pricing plans

A plan defines a monthly subscription price and how many successful payments a
merchant may process per calendar month under its AmatoPay contract.
Plan-covered payments have a 0% transaction fee; plans do not contain
per-transaction fee rates. Both the monthly price and transaction allowance can
be overridden on the assignment by the signed merchant contract.

Plans and effective-dated merchant assignments are managed in **Admin →
Pricing**. A plan applies only through a merchant's contract assignment;
inactive, future, and expired assignments are ignored.

The fee engine resolves pricing in this order:

1. Active merchant plan assignment for the transaction currency (0% fee).
2. Verification fee rule for a merchant without a plan.

The selected plan and assignment are stored on the checkout session, payment,
and immutable transaction-fee snapshot.

Create or refresh the standard AmatoPay Gateway plans with:

```bash
python manage.py seed_pricing_plans
```

Each plan contains an included successful-transaction allowance per calendar
month. The assignment's `contracted_transactions_per_month` can override that
allowance, making the signed merchant contract authoritative. A blank allowance
means unlimited or individually negotiated; it does not silently impose a cap.

## Verification rules

The initial administrator-managed rules are:

| Verification | Rate | Source |
| --- | ---: | --- |
| Partial or incomplete KYC/KYB | 3.00% | `VERIFICATION_PARTIAL` |
| Fully approved KYC/KYB | 2.00% | `VERIFICATION_VERIFIED` |

Verification rules remain the safe fallback for merchants when no matching
assigned plan exists. Operations can create a newly dated rule in
**Admin → Pricing → Verification fees**.

A merchant is `VERIFIED` only when:

- the merchant is active;
- its KYB decision is approved, `verified` is true, and `verified_at` exists;
- registration, tax, and representative-ID documents all exist, are verified,
  and are not expired.

Every other state—including missing, pending, rejected, suspended, unverified,
or expired requirements—is `PARTIAL`.

## Calculation

```text
fee = gross amount × applied percentage ÷ 100
merchant net = gross amount − fee
```

Calculations use `Decimal` and round half-up to the project's two-decimal BIF
money precision.

For 100,000 BIF:

```text
PARTIAL:   gross 100,000 − fee 3,000 = merchant net 97,000 BIF
VERIFIED:  gross 100,000 − fee 2,000 = merchant net 98,000 BIF
PLAN:      gross 100,000 − fee 0 = merchant net 100,000 BIF
```

## Merchant quote API

```http
GET /api/v1/fees/quote/?amount=100000&currency=BIF
X-Api-Key: sk_...
```

```json
{
  "amount": "100000.00",
  "currency": "BIF",
  "merchant_verification": "VERIFIED",
  "fee_rate": "2.00",
  "fee_amount": "2000.00",
  "net_amount": "98000.00",
  "fee_source": "VERIFICATION_VERIFIED"
}
```

When a plan covers the payment, `fee_source` is `PRICING_PLAN`, the fee is zero,
and the response also includes the plan code in `pricing_plan`.

Fee fields submitted by a client during Checkout Session creation are ignored;
the backend always resolves them again.

## Accounting workflow

1. Checkout Session creation resolves the current plan or verification rate.
2. The decision and exact rule references are snapshotted on the session.
3. Payment/collection acceptance copies the decision and creates one immutable
   `TransactionFee` record under a row lock.
4. The payer's gross amount enters protected fiduciary funds.
5. Secure delivery confirmation creates a settlement for the snapshotted net.
6. P2P sends only the merchant net to the verified settlement account.
7. Completed P2P posts exactly one merchant-release debit and one AmatoPay-fee
   debit. Together they equal the original gross amount.
8. Historical records are never recalculated after KYB, plan, or rule
   changes.
