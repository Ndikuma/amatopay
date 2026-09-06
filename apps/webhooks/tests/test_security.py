from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.webhooks.security import validate_webhook_url


@override_settings(WEBHOOK_ALLOW_INSECURE_URLS=False)
class StrictWebhookUrlTests(SimpleTestCase):
    def test_https_public_host_ok(self):
        url = "https://merchant.example/hooks/amatopay"
        self.assertEqual(validate_webhook_url(url), url)

    def test_http_rejected(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("http://merchant.example/hooks")

    def test_localhost_rejected(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("https://localhost:8000/hooks")

    def test_private_ip_rejected(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("https://127.0.0.1/hooks")


@override_settings(WEBHOOK_ALLOW_INSECURE_URLS=True)
class InsecureWebhookUrlTests(SimpleTestCase):
    def test_http_localhost_ok(self):
        url = "http://localhost:8000/api/payments/amatopay-webhook/tok/"
        self.assertEqual(validate_webhook_url(url), url)

    def test_http_private_ip_ok(self):
        url = "http://127.0.0.1:8000/hooks"
        self.assertEqual(validate_webhook_url(url), url)

    def test_still_rejects_non_http_scheme(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("ftp://localhost/hooks")
