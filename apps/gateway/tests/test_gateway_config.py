from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.gateway.admin import GatewayConfigForm
from apps.gateway.models import GatewayConfig


class GatewayConfigTests(TestCase):
    def config(self, name, **overrides):
        values = {
            "name": name,
            "base_url": "https://mobilecash.example/",
            "username": "gateway-user",
            "password": "gateway-password",
            "creditor_alias": "+25761000000",
        }
        values.update(overrides)
        return GatewayConfig.objects.create(**values)

    def test_activating_gateway_deactivates_previous_gateway(self):
        first = self.config("First", is_active=True)
        second = self.config("Second", is_active=True)

        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(GatewayConfig.active(), second)

    def test_mobilecash_configuration_requires_credentials(self):
        config = GatewayConfig(
            base_url="https://mobilecash.example",
        )
        with self.assertRaises(ValidationError):
            config.full_clean()

    def test_admin_edit_keeps_existing_hidden_password(self):
        config = self.config("Primary")
        form = GatewayConfigForm(
            instance=config,
            data={
                "name": config.name,
                "base_url": config.base_url,
                "username": config.username,
                "password": "",
                "creditor_alias": config.creditor_alias,
                "timeout_seconds": 15,
                "verify_tls": True,
                "is_active": True,
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["password"], "gateway-password")
