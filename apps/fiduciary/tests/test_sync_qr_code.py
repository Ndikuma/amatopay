from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.fiduciary.models import FiduciaryQRCode, FiduciaryQRExtension
from apps.fiduciary.services import sync_fiduciary_qr_code
from apps.gateway.models import GatewayConfig


class SyncFiduciaryQRCodeTests(TestCase):
    def setUp(self):
        self.config = GatewayConfig.objects.create(
            name="Primary gateway",
            base_url="https://gateway.example",
            username="amatopay",
            password="secret",
            creditor_alias="+25761000000",
            qr_code_text="00020101...AMATOPAY_QR...6304ABCD",
            is_active=True,
        )
        self.scan_response = {
            "rowid": 7,
            "qrHeaderUUID": "HEADER-1",
            "qrType": "STAT",
            "amountType": "FIXED",
            "currency": "BIF",
            "pmtContext": "ECOM",
            "isoVer": 1,
            "qrAsText": "00020101...",
            "qrAsImage": "data:image/png;base64,AAAA",
            "status": "active",
            "createdAt": "2026-09-01T09:00:00Z",
            "expiresAt": "2027-09-01T09:00:00Z",
            "lastSyncedAt": "2026-09-11T09:35:09.226Z",
            "creditorAlias": "+25761000000",
            "merchantCode": "AMATOPAY",
            "syncMessage": "OK",
            "isLocked": False,
            "lockTtl": 30,
            "lockedAt": None,
            "lockedBy": "",
            "lockExpiresAt": None,
            "lockReleaseRequired": False,
            "qrExtensionUUID": "EXT-1",
            "ttl": {"length": 90, "units": "DAYS"},
            "creditorName": "AmatoPay SA",
            "creditorAccount": "100200300",
            "creditorAgentBic": "CECFBI",
            "creditorAgentCodeType": "BIC",
            "isOurInstitution": True,
            "amount": None,
            "amountMin": 100,
            "amountMax": 5000000,
            "dba": "AmatoPay",
            "endToEnd": "E2E-1",
            "mcc": "6012",
            "bankOpCode": "OP1",
            "ttc": "TTC-1",
            "creditorRef": "REF-1",
            "customerType": "ORG",
            "taxId": "TAX-1",
            "countryOfResidence": "BI",
            "redirectUrl": "https://amatopay.bi/qr/redirect",
            "remittanceInfo": "AmatoPay collection",
            "extensions": [
                {
                    "rowid": 1,
                    "qrExtensionUUID": "EXT-1",
                    "isLast": False,
                    "status": "active",
                    "creditorName": "AmatoPay SA",
                    "creditorAccount": "100200300",
                    "amount": None,
                    "remittanceInfo": "Extension 1",
                    "ttlLength": 30,
                    "ttlUnits": "DAYS",
                    "createdAt": "2026-09-01T09:00:00Z",
                    "lastSyncedAt": "2026-09-11T09:35:09.226Z",
                },
                {
                    "rowid": 2,
                    "qrExtensionUUID": "EXT-2",
                    "isLast": True,
                    "status": "active",
                    "creditorName": "AmatoPay SA",
                    "creditorAccount": "100200300",
                    "amount": None,
                    "remittanceInfo": "Extension 2",
                    "ttlLength": 30,
                    "ttlUnits": "DAYS",
                    "createdAt": "2026-09-01T09:00:00Z",
                    "lastSyncedAt": "2026-09-11T09:35:09.226Z",
                },
            ],
        }

    @patch("apps.fiduciary.services.client.qr_scan")
    def test_sync_creates_qr_code_and_extensions(self, qr_scan):
        qr_scan.return_value = {"provider": self.scan_response}

        qr_code = sync_fiduciary_qr_code()

        qr_scan.assert_called_once_with("00020101...AMATOPAY_QR...6304ABCD", wait_seconds=120)
        self.assertEqual(FiduciaryQRCode.objects.count(), 1)
        self.assertEqual(qr_code.qr_header_uuid, "HEADER-1")
        self.assertEqual(qr_code.qr_type, "STAT")
        self.assertEqual(qr_code.creditor_alias, "+25761000000")
        self.assertEqual(qr_code.creditor_agent_bic, "CECFBI")
        self.assertEqual(qr_code.ttl_length, 90)
        self.assertEqual(qr_code.ttl_units, "DAYS")
        self.assertEqual(qr_code.amount_min, 100)
        self.assertIsNotNone(qr_code.provider_created_at)
        self.assertIsNotNone(qr_code.expires_at)
        self.assertEqual(qr_code.raw_response, self.scan_response)

        self.assertEqual(qr_code.extensions.count(), 2)
        ext = qr_code.extensions.get(qr_extension_uuid="EXT-2")
        self.assertTrue(ext.is_last)
        self.assertEqual(ext.remittance_info, "Extension 2")

    @patch("apps.fiduciary.services.client.qr_scan")
    def test_sync_is_a_singleton_and_drops_stale_extensions(self, qr_scan):
        qr_scan.return_value = {"provider": self.scan_response}
        sync_fiduciary_qr_code()
        self.assertEqual(FiduciaryQRExtension.objects.count(), 2)

        # Second sync only returns one of the two previous extensions.
        second_response = dict(self.scan_response)
        second_response["extensions"] = [self.scan_response["extensions"][0]]
        qr_scan.return_value = {"provider": second_response}

        sync_fiduciary_qr_code()

        self.assertEqual(FiduciaryQRCode.objects.count(), 1)
        self.assertEqual(FiduciaryQRExtension.objects.count(), 1)
        self.assertEqual(
            FiduciaryQRExtension.objects.get().qr_extension_uuid, "EXT-1"
        )

    @patch("apps.fiduciary.services.client.qr_scan")
    def test_sync_requires_qr_code_text(self, qr_scan):
        self.config.qr_code_text = ""
        self.config.save(update_fields=["qr_code_text"])

        with self.assertRaisesRegex(Exception, "no qr_code_text configured"):
            sync_fiduciary_qr_code()

        qr_scan.assert_not_called()


class SyncFiduciaryQRCodeCommandTests(TestCase):
    def setUp(self):
        GatewayConfig.objects.create(
            name="Primary gateway", base_url="https://gateway.example",
            username="u", password="p", creditor_alias="+25761000000",
            qr_code_text="00020101...AMATOPAY_QR...6304ABCD", is_active=True,
        )

    @patch("apps.fiduciary.services.client.qr_scan")
    def test_command_reports_success(self, qr_scan):
        qr_scan.return_value = {
            "provider": {"qrHeaderUUID": "HEADER-1", "status": "active", "extensions": []}
        }
        output = StringIO()

        call_command("sync_fiduciary_qr_code", stdout=output)

        self.assertIn("Synced QR code", output.getvalue())
        self.assertEqual(FiduciaryQRCode.objects.get().qr_header_uuid, "HEADER-1")

    def test_command_wraps_failure_as_command_error(self):
        GatewayConfig.objects.update(is_active=False)

        with self.assertRaises(CommandError):
            call_command("sync_fiduciary_qr_code")
