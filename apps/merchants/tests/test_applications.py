from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import RequestFactory
from django.urls import reverse

from apps.merchants.models import Merchant, MerchantApplication, MerchantApplicationReview


class MerchantApplicationTests(TestCase):
    payload = {
        "legal_name": "Example Commerce Burundi SA",
        "trading_name": "Example Commerce",
        "legal_form": "SA",
        "registration_number": "RC-12345",
        "tax_id": "NIF-98765",
        "industry": "Retail",
        "website": "https://example.bi",
        "country": "BI",
        "city": "Bujumbura",
        "address": "Rohero, Bujumbura",
        "contact_name": "Aline Example",
        "contact_role": "Director",
        "email": "aline@example.bi",
        "phone": "+25779123456",
        "expected_monthly_volume": "5000000",
        "expected_monthly_transactions": "200",
        "business_description": "We operate a local retail marketplace.",
        "payment_use_case": "Collect protected customer payments online.",
        "settlement_alias": "+25779123456",
        "settlement_account_name": "Example Commerce Burundi SA",
        "referral_source": "Partner",
        "company_website": "",
        "consent": "on",
        "password": "Safe-merchant-pass-2026!",
        "password_confirmation": "Safe-merchant-pass-2026!",
    }

    def test_public_application_creates_owner_account_and_pending_merchant(self):
        response = self.client.post(reverse("merchant_application"), self.payload)
        self.assertRedirects(
            response, reverse("merchant_application_received"),
            fetch_redirect_response=False,
        )
        application = MerchantApplication.objects.get()
        self.assertTrue(application.reference.startswith("AMA-"))
        self.assertEqual(application.status, MerchantApplication.Status.SUBMITTED)
        self.assertEqual(application.settlement_alias, "+25779123456")
        self.assertEqual(application.settlement_alias_type, "MOBILE")
        merchant = Merchant.objects.get()
        self.assertEqual(merchant.owner, application.applicant)
        self.assertEqual(merchant.status, Merchant.Status.PENDING_KYB)
        self.assertEqual(merchant.kyb.expected_monthly_transactions, 200)
        self.assertEqual(merchant.settlement_accounts.count(), 1)
        self.assertTrue(
            self.client.login(
                username=self.payload["email"], password=self.payload["password"]
            )
        )

        response = self.client.get(reverse("merchant_application_received"))
        self.assertContains(response, application.reference)

    def test_honeypot_rejects_automated_submission(self):
        payload = {**self.payload, "company_website": "spam.example"}
        response = self.client.post(reverse("merchant_application"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MerchantApplication.objects.count(), 0)

    def test_admin_status_change_creates_review_event(self):
        application = MerchantApplication.objects.create(
            **{
                key: value
                for key, value in self.payload.items()
                if key
                not in {
                    "consent",
                    "company_website",
                    "password",
                    "password_confirmation",
                }
            },
            consented_at="2026-08-09T10:00:00Z",
        )
        user = get_user_model().objects.create_superuser(
            username="reviewer", email="reviewer@amatopay.bi", password="test-pass"
        )
        from apps.merchants.admin import MerchantApplicationAdmin
        from django.contrib import admin

        request = RequestFactory().post("/admin/merchants/merchantapplication/")
        request.user = user
        application.status = MerchantApplication.Status.UNDER_REVIEW
        application.review_notes = "Initial compliance review started."
        MerchantApplicationAdmin(MerchantApplication, admin.site).save_model(
            request, application, form=None, change=True
        )
        event = MerchantApplicationReview.objects.get(application=application)
        self.assertEqual(event.previous_status, MerchantApplication.Status.SUBMITTED)
        self.assertEqual(event.new_status, MerchantApplication.Status.UNDER_REVIEW)
        self.assertEqual(event.actor, user)
