from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.security.models import RequestLog, SecurityAlert


class SecurityIntegrationTests(TestCase):
    databases = {"default", "security"}

    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="security-operator",
            password="safe-test-password-2026",
            is_staff=True,
        )

    def test_security_models_are_routed_to_isolated_database(self):
        log = RequestLog.objects.create(
            ip_address="127.0.0.1",
            method="GET",
            path="/api/v1/payments/",
            status_code=200,
            is_api=True,
        )
        self.assertEqual(log._state.db, "security")

    def test_security_dashboard_matches_amatopay_brand(self):
        self.client.force_login(self.staff)
        SecurityAlert.objects.create(
            severity="high",
            alert_type="scanning",
            ip_address="192.0.2.10",
            path="/.env",
            detail="Test alert",
        )

        response = self.client.get(reverse("security-dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AmatoPay")
        self.assertContains(response, "Security Center")
        self.assertContains(response, "192.0.2.10")
        self.assertContains(response, "/.env")
