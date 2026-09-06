from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminDashboardTests(TestCase):
    def test_operations_dashboard_renders_for_superuser(self):
        user = get_user_model().objects.create_superuser(
            username="dashboard-admin",
            email="operations@example.com",
            password="safe-test-password-2026",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operations overview")
        self.assertContains(response, "Funds protected")
        self.assertContains(response, "Gateway setup required")
        self.assertContains(response, "Recent payments")
        self.assertContains(response, "Payment volume")
        self.assertContains(response, "Payment status")
        self.assertContains(response, "Collections")
        self.assertContains(response, "Compliance &amp; platform")
        self.assertNotContains(response, "All controls")
