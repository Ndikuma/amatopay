import hashlib
import hmac
import json
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.merchants.models import Merchant, MerchantWebhookEndpoint
from apps.webhooks.models import WebhookAttempt, WebhookDelivery
from apps.webhooks.services import deliver, emit_event


class WebhookDeliveryTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-WEBHOOK-TEST",
            legal_name="Webhook Test",
            display_name="Webhook Test",
            status=Merchant.Status.ACTIVE,
        )
        self.endpoint = MerchantWebhookEndpoint.objects.create(
            merchant=self.merchant,
            url="https://merchant.example/webhooks/amatopay",
            secret="whsec_test_secret",
            events=["payment.paid"],
        )

    def delivery(self):
        event = emit_event(
            self.merchant,
            "payment.paid",
            {"payment_reference": "AMP-PAY-1", "amount": "10000.00"},
            "payment",
            "AMP-PAY-1",
        )
        return WebhookDelivery.objects.get(event=event, endpoint=self.endpoint)

    @patch("apps.webhooks.services.validate_webhook_url")
    @patch("apps.webhooks.services.requests.post")
    def test_success_is_signed_and_attempt_is_audited(self, post, validate_url):
        post.return_value = Mock(status_code=204, text="", spec=["status_code", "text"])
        delivery = deliver(self.delivery())

        self.assertEqual(delivery.status, WebhookDelivery.Status.DELIVERED)
        attempt = WebhookAttempt.objects.get(delivery=delivery)
        self.assertTrue(attempt.succeeded)
        self.assertEqual(attempt.response_status, 204)
        sent = post.call_args
        body = sent.kwargs["data"]
        signature = sent.kwargs["headers"]["AmatoPay-Signature"]
        timestamp, digest = signature.replace("t=", "").replace("v1=", "").split(",")
        expected = hmac.new(
            self.endpoint.secret.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual(json.loads(body), delivery.event.payload)

    @patch("apps.webhooks.services.validate_webhook_url")
    @patch("apps.webhooks.services.requests.post")
    def test_failure_is_scheduled_and_each_retry_has_history(self, post, validate_url):
        post.return_value = Mock(status_code=503, text="unavailable", spec=["status_code", "text"])
        delivery = deliver(self.delivery())
        self.assertEqual(delivery.status, WebhookDelivery.Status.RETRYING)
        self.assertIsNotNone(delivery.next_retry_at)
        self.assertEqual(delivery.attempts, 1)

        delivery.next_retry_at = None
        delivery.save(update_fields=["next_retry_at", "updated_at"])
        delivery = deliver(delivery)
        self.assertEqual(delivery.attempts, 2)
        self.assertEqual(
            list(delivery.attempt_history.order_by("attempt_number").values_list("attempt_number", flat=True)),
            [1, 2],
        )

    def test_event_subscription_filter_is_enforced(self):
        emit_event(self.merchant, "settlement.completed", {}, "settlement", "STL-1")
        self.assertFalse(WebhookDelivery.objects.exists())
