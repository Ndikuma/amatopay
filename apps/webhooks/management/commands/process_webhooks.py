import time

from django.core.management.base import BaseCommand
from apps.webhooks.services import deliver_pending


class Command(BaseCommand):
    help = "Deliver pending AmatoPay merchant webhooks."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=10)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["interval"] < 5:
            raise ValueError("--interval must be at least 5 seconds")
        while True:
            count = deliver_pending(options["limit"])
            self.stdout.write(f"Delivered/attempted {count} webhook deliveries")
            if not options["watch"]:
                break
            time.sleep(options["interval"])
