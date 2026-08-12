from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.fiduciary.models import FiduciaryAccount
from apps.gateway.models import GatewayConfig


class SyncFiduciaryAccountCommandTests(TestCase):
    def setUp(self):
        self.config = GatewayConfig.objects.create(
            name="Primary gateway",
            base_url="https://gateway.example",
            username="amatopay",
            password="secret",
            creditor_alias="+25761000000",
            is_active=True,
        )
        self.verification = {
            "found": True,
            "status": "ACTIVE",
            "customer": {"name": "AmatoPay Fiduciary"},
            "account": {
                "type": "MOBILE",
                "number": "100200300",
                "name": "AmatoPay Fiduciary",
                "currency": "BIF",
            },
            "provider": {"defaultAccount": "100200300"},
        }

    @patch("apps.fiduciary.management.commands.sync_fiduciary_account.client.verify_alias")
    def test_command_creates_and_updates_one_verified_account(self, verify_alias):
        verify_alias.return_value = self.verification
        output = StringIO()

        call_command("sync_fiduciary_account", stdout=output)
        account = FiduciaryAccount.objects.get()

        self.assertEqual(account.creditor_alias, "+25761000000")
        self.assertEqual(account.account_number, "100200300")
        self.assertIsNotNone(account.verified_at)
        self.assertTrue(account.is_verified)
        self.assertIn("Created fiduciary account", output.getvalue())

        self.verification["account"]["name"] = "AmatoPay Protected Funds"
        call_command("sync_fiduciary_account", stdout=output)
        self.assertEqual(FiduciaryAccount.objects.count(), 1)
        account.refresh_from_db()
        self.assertEqual(account.account_name, "AmatoPay Protected Funds")

    @patch("apps.fiduciary.management.commands.sync_fiduciary_account.client.verify_alias")
    def test_command_rejects_verification_without_account_number(self, verify_alias):
        self.verification["account"]["number"] = ""
        verify_alias.return_value = self.verification

        with self.assertRaisesRegex(CommandError, "did not return an account number"):
            call_command("sync_fiduciary_account")

        self.assertFalse(FiduciaryAccount.objects.exists())
