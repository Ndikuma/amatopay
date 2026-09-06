"""Catalogue of AmatoPay webhook event types a merchant can subscribe to.

Every value here must correspond to an ``emit_event(...)`` call somewhere in the
codebase. ``endpoint.test`` is deliberately excluded: it is an internal test
ping that the dashboard force-delivers to a single endpoint.
"""

WEBHOOK_EVENTS = {
    "payment.processing": "Payer approved the request; collection is in progress.",
    "payment.awaiting_approval": "The payment collection is waiting for the payer to approve it.",
    "payment.paid": "Funds were collected and are now protected.",
    "payment.failed": "The payment was rejected, failed, or cancelled.",
    "delivery.confirmed": "The customer confirmed delivery with their secure code.",
    "payment.disputed": "The customer opened a delivery investigation; funds are frozen.",
    "settlement.completed": "Net funds were released and paid to the merchant.",
    "settlement.failed": "A merchant payout attempt failed.",
    "payment.refunded": "A refund on the payment completed.",
}

WEBHOOK_EVENT_TYPES = frozenset(WEBHOOK_EVENTS)
