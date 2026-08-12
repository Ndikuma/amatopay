from django.test import RequestFactory, TestCase
from rest_framework.exceptions import AuthenticationFailed

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.merchants.models import Merchant, MerchantApiKey


class MerchantApiKeyTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-KEY-TEST",
            legal_name="Key Test",
            display_name="Key Test",
            status="active",
        )
        self.key, self.raw = MerchantApiKey.issue(self.merchant, "Integration")
        self.auth = MerchantApiKeyAuthentication()
        self.factory = RequestFactory()

    def test_x_api_key_header_authenticates(self):
        request = self.factory.get("/api/v1/payments/", HTTP_X_API_KEY=self.raw)
        _, key = self.auth.authenticate(request)
        self.assertEqual(key, self.key)
        self.assertEqual(request.merchant, self.merchant)

    def test_bearer_header_authenticates(self):
        request = self.factory.get(
            "/api/v1/payments/", HTTP_AUTHORIZATION=f"Bearer {self.raw}"
        )
        _, key = self.auth.authenticate(request)
        self.assertEqual(key, self.key)

    def test_rotation_invalidates_previous_secret(self):
        replacement = self.key.rotate()
        self.assertNotEqual(replacement, self.raw)
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self.factory.get("/", HTTP_X_API_KEY=self.raw))
        _, key = self.auth.authenticate(
            self.factory.get("/", HTTP_X_API_KEY=replacement)
        )
        self.assertEqual(key, self.key)

    def test_revoke_disables_key(self):
        self.key.revoke()
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self.factory.get("/", HTTP_X_API_KEY=self.raw))

    def test_plaintext_secret_is_not_stored(self):
        self.key.refresh_from_db()
        self.assertNotEqual(self.key.secret_hash, self.raw)
        self.assertNotIn(self.raw, str(self.key.__dict__))
