from django.core.management.base import BaseCommand, CommandError

from apps.fiduciary.services import sync_fiduciary_qr_code


class Command(BaseCommand):
    help = (
        "Scan AmatoPay's own registered QR code and synchronize the single "
        "FiduciaryQRCode record (header/extension UUIDs, lock state, TTL, "
        "creditor/remittance detail)."
    )

    def handle(self, *args, **options):
        try:
            qr_code = sync_fiduciary_qr_code()
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced QR code for creditor alias {qr_code.creditor_alias!r} "
                f"(header={qr_code.qr_header_uuid}, status={qr_code.status!r}, "
                f"extensions={qr_code.extensions.count()})."
            )
        )
