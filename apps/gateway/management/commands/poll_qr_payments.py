import logging
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.fiduciary.models import FiduciaryAccount
from apps.gateway import client
from apps.gateway.models import GatewayConfig, QRPaymentWatch
from apps.payments.services import record_qr_collection

logger = logging.getLogger(__name__)

MAX_PAGES = 5
PAGE_SIZE = 100
LOOKBACK_BUFFER = timedelta(minutes=5)


class Command(BaseCommand):
    help = (
        "Discover a transaction against a watched QR payment by searching "
        "AmatoPay's own transaction ledger (GET /api/MobileTrxPay/paged, "
        "filtered to our ReceiverAlias). This is discovery ONLY: once a "
        "trxRef is found, it is handed off to the existing "
        "GatewayRequest/reconcile_gateway machinery (untouched) for status "
        "resolution via TRANSACTION_BY_REFERENCE — exactly like every other "
        "collection."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=5)

    def handle(self, *args, **options):
        if options["interval"] < 3:
            raise ValueError("--interval must be at least 3 seconds")
        while True:
            self._poll(options["limit"])
            if not options["watch"]:
                break
            time.sleep(options["interval"])

    def _poll(self, limit):
        now = timezone.now()
        due = (
            QRPaymentWatch.objects.select_related("payment", "payment__session")
            .filter(status=QRPaymentWatch.Status.WATCHING)
            .filter(Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now))
            .order_by("created_at")[:limit]
        )
        checked = discovered = expired = failed = 0
        for watch in due:
            checked += 1
            try:
                outcome = self._poll_one(watch, now)
            except Exception as exc:
                failed += 1
                logger.exception("Could not poll QR watch %s", watch.pk)
                self.stderr.write(f"{watch.pk}: {exc}")
                continue
            if outcome == "discovered":
                discovered += 1
            elif outcome == "expired":
                expired += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"QR poll complete: checked={checked}, discovered={discovered}, "
                f"expired={expired}, failed={failed}"
            )
        )

    def _poll_one(self, watch, now):
        session = watch.payment.session
        if session.expires_at and session.expires_at <= now:
            watch.status = QRPaymentWatch.Status.EXPIRED
            watch.last_polled_at = now
            watch.save(update_fields=["status", "last_polled_at", "updated_at"])
            return "expired"

        trx_ref = None
        try:
            trx_ref = self._discover(watch, now)
        except Exception as exc:
            failures = watch.consecutive_poll_failures + 1
            status_code = getattr(exc, "status_code", None)
            base_delay = 30 if status_code == 429 else 10
            delay = min(base_delay * (2 ** (failures - 1)), 300)
            watch.last_polled_at = now
            watch.next_poll_at = now + timedelta(seconds=delay)
            watch.poll_attempts += 1
            watch.consecutive_poll_failures = failures
            watch.last_poll_error = str(exc)[:2000]
            watch.save(
                update_fields=[
                    "last_polled_at",
                    "next_poll_at",
                    "poll_attempts",
                    "consecutive_poll_failures",
                    "last_poll_error",
                    "updated_at",
                ]
            )
            raise

        watch.last_polled_at = now
        watch.poll_attempts += 1
        watch.consecutive_poll_failures = 0
        watch.last_poll_error = ""

        if not trx_ref:
            watch.next_poll_at = now + timedelta(seconds=5)
            watch.save(
                update_fields=[
                    "last_polled_at",
                    "poll_attempts",
                    "consecutive_poll_failures",
                    "last_poll_error",
                    "next_poll_at",
                    "updated_at",
                ]
            )
            return "pending"

        watch.status = QRPaymentWatch.Status.MATCHED
        watch.matched_trx_ref = trx_ref
        watch.save(
            update_fields=[
                "status",
                "matched_trx_ref",
                "last_polled_at",
                "poll_attempts",
                "consecutive_poll_failures",
                "last_poll_error",
                "updated_at",
            ]
        )
        record_qr_collection(watch.payment, trx_ref)
        return "discovered"

    @staticmethod
    def _discover(watch, now):
        """Search our own receiver ledger for the transaction this QR watch
        is waiting on, and accept a match only if it's unambiguous.

        The gateway used to stamp the shared QR's header/extension UUID onto
        each resulting transaction, letting us look transactions up by that
        UUID directly. It no longer does, so instead we pull every recent
        transaction paid *to us*, narrowed server-side to this payment's
        amount and the window since the watch was opened, then keep only
        QR-originated rows (``isQrPayment``) so a same-amount alias-push
        collection can never be mistaken for this QR sighting.

        "Paid to us" has two spellings at the gateway: the creditor *alias*
        (``GatewayConfig.creditor_alias``, e.g. a phone number) and the raw
        settlement *account number* behind it (``FiduciaryAccount.
        account_number``) — a transaction can land under either as
        ``ReceiverAlias``, so both are searched and merged.

        AmatoPay's QR is shared across every QR-enabled merchant, so more
        than one QR payment can still land at the same amount in the same
        window — amount is the only signal the payer's banking app can echo
        back, so an ambiguous (>1) match is left for a later poll rather
        than guessed.

        Returns the matched trxRef, or None if nothing matched yet.
        """
        config = GatewayConfig.active()
        if not config or not config.creditor_alias:
            return None
        expected_amount = watch.payment.amount
        from_date = (watch.created_at - LOOKBACK_BUFFER).isoformat()
        to_date = now.isoformat()

        receiver_candidates = [config.creditor_alias]
        account = FiduciaryAccount.objects.filter(
            creditor_alias=config.creditor_alias, active=True
        ).first()
        if account and account.account_number:
            if account.account_number not in receiver_candidates:
                receiver_candidates.append(account.account_number)

        candidates = []
        seen_refs = set()
        for receiver_alias in receiver_candidates:
            page = 1
            while page <= MAX_PAGES:
                result = client.list_transactions_paged(
                    receiver_alias=receiver_alias,
                    from_date=from_date,
                    to_date=to_date,
                    min_amount=float(expected_amount),
                    max_amount=float(expected_amount),
                    page_number=page,
                    page_size=PAGE_SIZE,
                )
                for txn in result.get("transactions", []):
                    if not txn.get("isQrPayment"):
                        continue
                    if txn["trxRef"] in seen_refs:
                        continue
                    seen_refs.add(txn["trxRef"])
                    candidates.append(txn)
                total_pages = result.get("total_pages", 1)
                if page >= total_pages:
                    break
                page += 1

        matches = []
        for txn in candidates:
            amount = txn.get("amount")
            if amount is None:
                continue
            try:
                if Decimal(str(amount)) == Decimal(str(expected_amount)):
                    matches.append(txn)
            except InvalidOperation:
                continue

        if len(matches) == 1:
            return matches[0]["trxRef"]
        return None
