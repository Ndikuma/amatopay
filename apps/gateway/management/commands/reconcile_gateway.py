import logging
import time

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.gateway.models import P2PRequest, RTPRequest
from apps.gateway.services import (
    recover_p2p_status,
    recover_rtp_status,
    start_merchant_payout,
)
from apps.settlements.models import Settlement

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Poll MobileCash transaction references for RTP and P2P status updates."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=20)

    def handle(self, *args, **options):
        if options["interval"] < 5:
            raise ValueError("--interval must be at least 5 seconds")
        while True:
            self._reconcile(options["limit"])
            if not options["watch"]:
                break
            time.sleep(options["interval"])

    def _reconcile(self, limit):
        now = timezone.now()
        ready_settlements = (
            Settlement.objects.select_related("payment", "merchant")
            .filter(
                status="pending",
                payment__fund_hold__status="release_pending",
                p2p__isnull=True,
            )
            .order_by("created_at")[:limit]
        )
        for settlement in ready_settlements:
            try:
                start_merchant_payout(settlement)
            except Exception as exc:
                logger.exception(
                    "Could not start settlement P2P %s", settlement.reference
                )
                self.stderr.write(f"{settlement.reference}: {exc}")
        pending = (
            RTPRequest.objects.select_related("payment")
            .filter(status__in=["pending", "awaiting_approval", "processing"])
            .filter(Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now))
            .exclude(provider_reference="")
            .order_by("created_at")[:limit]
        )
        checked = updated = failed = 0
        rate_limited = False
        for rtp in pending:
            checked += 1
            try:
                if recover_rtp_status(rtp):
                    updated += 1
            except Exception as exc:
                failed += 1
                if getattr(exc, "status_code", None) == 429:
                    rate_limited = True
                logger.exception("Could not reconcile RTP %s", rtp.request_id)
                self.stderr.write(f"{rtp.request_id}: {exc}")
                if rate_limited:
                    self.stderr.write("Gateway rate limit reached; ending this poll cycle early.")
                    break
        pending_payouts = (
            P2PRequest.objects.select_related("settlement", "settlement__payment")
            .filter(status__in=["pending", "processing", "awaiting_approval"])
            .filter(Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now))
            .exclude(provider_reference="")
            .order_by("created_at")[:limit]
        )
        payouts_to_poll = [] if rate_limited else pending_payouts
        for p2p in payouts_to_poll:
            checked += 1
            try:
                if recover_p2p_status(p2p):
                    updated += 1
            except Exception as exc:
                failed += 1
                if getattr(exc, "status_code", None) == 429:
                    rate_limited = True
                logger.exception("Could not reconcile P2P %s", p2p.request_id)
                self.stderr.write(f"{p2p.request_id}: {exc}")
                if rate_limited:
                    self.stderr.write("Gateway rate limit reached; ending this poll cycle early.")
                    break
        self.stdout.write(
            self.style.SUCCESS(
                f"Gateway reconciliation complete: checked={checked}, updated={updated}, failed={failed}"
            )
        )
