"""Submit collections for checkout payments that were created without
waiting for the gateway.

Merchant checkout creation records the Payment at ``alias_verified`` and returns
immediately. This command picks those up and submits the collection to MobileCash.
``reconcile_gateway`` then polls each request through to a terminal state.

Run on a short schedule (e.g. every minute) alongside ``reconcile_gateway``.
"""

import logging
import time

from django.core.management.base import BaseCommand

from apps.gateway.collection import PaymentGatewayError
from apps.payments.models import Payment
from apps.payments.services import submit_checkout_payment_collection

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Submit collections for checkout payments awaiting the gateway."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=15)

    def handle(self, *args, **options):
        if options["interval"] < 5:
            raise ValueError("--interval must be at least 5 seconds")
        while True:
            self._process(options["limit"])
            if not options["watch"]:
                break
            time.sleep(options["interval"])

    def _process(self, limit):
        pending = (
            Payment.objects.filter(
                status=Payment.Status.ALIAS_VERIFIED,
                session__isnull=False,
            )
            .select_related("session", "merchant")
            .order_by("created_at")[:limit]
        )
        submitted = failed = 0
        for payment in pending:
            try:
                submit_checkout_payment_collection(payment)
                submitted += 1
            except PaymentGatewayError as exc:
                failed += 1
                logger.warning("Collection submit deferred for %s: %s", payment.reference, exc)
            except Exception as exc:  # noqa: BLE001 - keep the batch running
                failed += 1
                logger.exception("Could not submit collection for %s", payment.reference)
                self.stderr.write(f"{payment.reference}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Pending payments processed: submitted={submitted}, failed={failed}"
            )
        )
