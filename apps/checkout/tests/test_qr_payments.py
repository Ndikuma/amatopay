from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import PricingPlan
from apps.checkout.models import PaymentSession
from apps.checkout.serializers import PaymentSessionSerializer, QRPaymentSessionSerializer
from apps.checkout.services import create_qr_checkout_session
from apps.fiduciary.models import FiduciaryAccount
from apps.gateway.models import GatewayConfig, GatewayRequest, QRPaymentWatch
from apps.gateway.provider import MobileCashGatewayError
from apps.gateway.services import AliasNotPayableError, recover_collection_status
from apps.merchants.models import Merchant, MerchantApiKey
from apps.payments.models import Payment


class _Req:
    def __init__(self, merchant):
        self.merchant = merchant


class QRSerializerGatingTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-QR-1", legal_name="Shop Co", display_name="Shop Co",
            status=Merchant.Status.ACTIVE,
        )

    def _payload(self, **over):
        base = {
            "order_number": "QR-1", "description": "QR order",
            "amount": "5000.00", "currency": "BIF", "payer_alias": "+25779000000",
        }
        base.update(over)
        return base

    def test_qr_session_rejected_when_merchant_not_enabled(self):
        s = QRPaymentSessionSerializer(data=self._payload(), context={"request": _Req(self.merchant)})
        self.assertFalse(s.is_valid())
        self.assertIn("non_field_errors", s.errors)

    def test_qr_session_requires_payer_alias(self):
        payload = self._payload()
        del payload["payer_alias"]
        s = QRPaymentSessionSerializer(data=payload, context={"request": _Req(self.merchant)})
        self.assertFalse(s.is_valid())
        self.assertIn("payer_alias", s.errors)

    def test_qr_session_valid_with_payer_alias_when_merchant_enabled(self):
        self.merchant.qr_payments_enabled = True
        self.merchant.save(update_fields=["qr_payments_enabled"])
        s = QRPaymentSessionSerializer(data=self._payload(), context={"request": _Req(self.merchant)})
        self.assertTrue(s.is_valid(), s.errors)

    def test_alias_session_still_requires_payer_alias(self):
        s = PaymentSessionSerializer(
            data={
                "order_number": "AL-1", "description": "Alias order",
                "amount": "5000.00", "currency": "BIF",
            },
            context={"request": _Req(self.merchant)},
        )
        self.assertFalse(s.is_valid())
        self.assertIn("payer_alias", s.errors)


class QRCheckoutServiceTests(TestCase):
    databases = {"default", "security"}

    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-QR-2", legal_name="Shop Co", display_name="Shop Co",
            status=Merchant.Status.ACTIVE, qr_payments_enabled=True,
        )
        GatewayConfig.objects.create(
            name="Primary", base_url="https://mobilecash.example",
            username="u", password="p", creditor_alias="+25761000000",
            qr_code_text="00020101...AMATOPAY_QR...6304ABCD", is_active=True,
        )
        PricingPlan.objects.create(
            code="pay-as-you-go", name="Pay as you go", currency="BIF",
            active=True, transaction_fee_percentage=Decimal("5"),
        )

    def _verify_alias_response(self, **over):
        base = {
            "found": True,
            "status": "ACTIVE",
            "customer": {"name": "Known Customer", "reference": "cust-7"},
            "account": {"type": "MOBILE", "currency": "BIF"},
        }
        base.update(over)
        return base

    @patch("apps.payments.services.client.qr_scan")
    @patch("apps.gateway.services.client.verify_alias")
    def test_qr_session_verifies_payer_alias_upfront_and_opens_a_watch(self, verify_alias, qr_scan):
        verify_alias.return_value = self._verify_alias_response()
        qr_scan.return_value = {
            "qrHeaderUUID": "HEADER-2",
            "qrExtensionUUIDs": ["EXT-1", "EXT-2"],
            "qrType": "STAT",
            "status": "active",
            "isLocked": False,
            "creditorAlias": "+25761000000",
            "provider": {},
        }

        session = create_qr_checkout_session(
            merchant=self.merchant,
            session_data={
                "order_number": "QR-3", "description": "In-store order",
                "amount": Decimal("5000.00"), "currency": "BIF",
            },
            payer_alias="+25779001234",
        )

        verify_alias.assert_called_once()
        qr_scan.assert_called_once_with("00020101...AMATOPAY_QR...6304ABCD")
        self.assertEqual(session.payer_alias, "+25779001234")
        self.assertEqual(session.payer_display_name, "Known Customer")
        self.assertEqual(session.alias_verifications.count(), 1)

        payment = session.payment
        self.assertEqual(payment.status, Payment.Status.QR_PENDING)
        self.assertEqual(payment.payer_alias, "+25779001234")
        self.assertEqual(payment.payer_alias_type, "MOBILE")
        self.assertEqual(payment.payer_display_name, "Known Customer")
        self.assertEqual(payment.payer_reference, "cust-7")

        watch = payment.qr_watch
        self.assertEqual(watch.qr_header_uuid, "HEADER-2")
        self.assertEqual(watch.qr_extension_uuids, ["EXT-1", "EXT-2"])
        self.assertEqual(watch.qr_type, "STAT")
        self.assertEqual(watch.status, QRPaymentWatch.Status.WATCHING)

    @patch("apps.gateway.services.client.verify_alias")
    def test_qr_session_rejects_an_unpayable_supplied_alias(self, verify_alias):
        verify_alias.return_value = {"found": False}

        with self.assertRaises(AliasNotPayableError):
            create_qr_checkout_session(
                merchant=self.merchant,
                session_data={
                    "order_number": "QR-4", "description": "In-store order",
                    "amount": Decimal("5000.00"), "currency": "BIF",
                },
                payer_alias="+25779999999",
            )
        self.assertFalse(PaymentSession.objects.filter(order_number="QR-4").exists())

    @patch("apps.payments.services.client.qr_scan")
    @patch("apps.gateway.services.client.verify_alias")
    def test_creditor_alias_mismatch_is_rejected(self, verify_alias, qr_scan):
        verify_alias.return_value = self._verify_alias_response()
        qr_scan.return_value = {
            "qrHeaderUUID": "HEADER-1",
            "qrExtensionUUIDs": ["EXT-1"],
            "creditorAlias": "+25799999999",  # not AmatoPay's own alias
            "provider": {},
        }

        with self.assertRaisesRegex(Exception, "creditor alias mismatch"):
            create_qr_checkout_session(
                merchant=self.merchant,
                session_data={
                    "order_number": "QR-BAD", "description": "QR order",
                    "amount": Decimal("5000.00"), "currency": "BIF",
                },
                payer_alias="+25779001234",
            )

    @patch("apps.payments.services.client.qr_scan")
    @patch("apps.gateway.services.client.verify_alias")
    def test_locked_qr_is_rejected(self, verify_alias, qr_scan):
        verify_alias.return_value = self._verify_alias_response()
        qr_scan.return_value = {
            "qrHeaderUUID": "HEADER-1", "qrExtensionUUIDs": ["EXT-1"],
            "isLocked": True, "provider": {},
        }

        with self.assertRaisesRegex(Exception, "currently in use"):
            create_qr_checkout_session(
                merchant=self.merchant,
                session_data={
                    "order_number": "QR-LOCKED", "description": "QR order",
                    "amount": Decimal("5000.00"), "currency": "BIF",
                },
                payer_alias="+25779001234",
            )


class PollQRPaymentsCommandTests(TestCase):
    databases = {"default", "security"}

    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-QR-3", legal_name="Shop Co", display_name="Shop Co",
            status=Merchant.Status.ACTIVE, qr_payments_enabled=True,
        )
        FiduciaryAccount.objects.create(
            creditor_alias="+25761000000", account_number="100200300",
            account_name="Fiduciary", currency="BIF",
            active=True, verified_at=timezone.now(),
        )
        GatewayConfig.objects.create(
            name="Primary", base_url="https://mobilecash.example",
            username="user", password="password", creditor_alias="+25761000000",
            is_active=True,
        )
        self.session = PaymentSession.objects.create(
            merchant=self.merchant, order_number="QR-3", description="QR order",
            amount=Decimal("5000.00"), payment_method=PaymentSession.PaymentMethod.QR,
            expires_at=timezone.now() + timedelta(hours=1),
            status=PaymentSession.Status.CREATED,
        )
        self.payment = Payment.objects.create(
            session=self.session, merchant=self.merchant, amount=self.session.amount,
            status=Payment.Status.QR_PENDING,
        )
        self.watch = QRPaymentWatch.objects.create(
            payment=self.payment, qr_header_uuid="HEADER-9", qr_extension_uuids=["EXT-9"],
        )

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_discovered_transaction_hands_off_to_existing_reconciler(self, list_paged):
        """poll_qr_payments only discovers the trxRef and creates a GatewayRequest —
        it must NOT resolve status itself. The existing (untouched)
        recover_collection_status is what finalizes the payment, exactly as
        it does for every alias-initiated collection."""
        list_paged.return_value = {
            "transactions": [
                {
                    "trxRef": "IPS-QR-1", "status": "PROCESSING", "amount": "5000.00",
                    "isQrPayment": True, "provider": {},
                }
            ]
        }

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.MATCHED)
        self.assertEqual(self.watch.matched_trx_ref, "IPS-QR-1")
        self.assertEqual(self.payment.status, Payment.Status.COLLECTION_PENDING)
        self.assertEqual(self.payment.provider_reference, "IPS-QR-1")

        collection = self.payment.collection
        self.assertEqual(collection.rail, GatewayRequest.Rail.COLLECTION)
        self.assertEqual(collection.provider_reference, "IPS-QR-1")
        # Discovered watches don't dictate the outcome — status starts
        # PROCESSING regardless of the discovery snapshot, so the reference
        # poll below is the actual source of truth.
        self.assertEqual(collection.status, "processing")

        # Prove the handoff actually works: the existing, untouched collection
        # reconciler resolves this exactly like any other collection.
        with patch("apps.gateway.services.client.get_collection_status") as get_status:
            get_status.return_value = {"status": "COMPLETED"}
            with self.captureOnCommitCallbacks(execute=True):
                recover_collection_status(collection)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.DELIVERY_PENDING)
        self.assertIsNotNone(self.payment.paid_at)
        self.assertTrue(hasattr(self.payment, "fund_hold"))

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_no_transaction_yet_reschedules_without_touching_other_watches(self, list_paged):
        list_paged.return_value = {"transactions": []}

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.WATCHING)
        self.assertIsNotNone(self.watch.next_poll_at)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.QR_PENDING)

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_transaction_with_wrong_amount_is_ignored(self, list_paged):
        """AmatoPay's QR is shared across merchants — a sighting that doesn't
        match the expected amount must not be accepted as this payment
        (self.payment.amount is 5000.00)."""
        list_paged.return_value = {
            "transactions": [
                {
                    "trxRef": "OTHER-MERCHANT-TXN", "status": "COMPLETED", "amount": "9999.00",
                    "isQrPayment": True, "provider": {},
                }
            ]
        }

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.WATCHING)
        self.assertFalse(GatewayRequest.objects.filter(provider_reference="OTHER-MERCHANT-TXN").exists())

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_non_qr_transaction_at_the_matching_amount_is_ignored(self, list_paged):
        """A regular alias-push collection lands under the same receiver
        alias and can share the expected amount — only rows the gateway
        flags as QR-originated may resolve a QR watch."""
        list_paged.return_value = {
            "transactions": [
                {
                    "trxRef": "ALIAS-COLLECTION-TXN", "status": "COMPLETED", "amount": "5000.00",
                    "isQrPayment": False, "provider": {},
                }
            ]
        }

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.WATCHING)

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_ambiguous_same_amount_matches_are_not_accepted(self, list_paged):
        """Two different concurrent transactions at the same expected amount
        can't be told apart — must be left for a later poll, not guessed."""
        list_paged.return_value = {
            "transactions": [
                {"trxRef": "TXN-A", "status": "COMPLETED", "amount": "5000.00", "isQrPayment": True, "provider": {}},
                {"trxRef": "TXN-B", "status": "COMPLETED", "amount": "5000.00", "isQrPayment": True, "provider": {}},
            ]
        }

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.WATCHING)

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_only_the_matching_amount_among_several_is_accepted(self, list_paged):
        list_paged.return_value = {
            "transactions": [
                {"trxRef": "OTHER-TXN", "status": "COMPLETED", "amount": "1000.00", "isQrPayment": True, "provider": {}},
                {"trxRef": "MY-TXN", "status": "PROCESSING", "amount": "5000.00", "isQrPayment": True, "provider": {}},
            ]
        }

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.MATCHED)
        self.assertEqual(self.watch.matched_trx_ref, "MY-TXN")

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_search_is_scoped_to_our_receiver_alias_and_expected_amount(self, list_paged):
        list_paged.return_value = {"transactions": []}

        call_command("poll_qr_payments", "--limit", "10")

        self.assertEqual(list_paged.call_count, 2)
        for call in list_paged.call_args_list:
            self.assertEqual(call.kwargs["min_amount"], 5000.0)
            self.assertEqual(call.kwargs["max_amount"], 5000.0)

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_search_covers_both_alias_and_account_number_as_receiver(self, list_paged):
        """A transaction can be recorded at the gateway with either
        AmatoPay's alias or its raw account number as ``ReceiverAlias`` —
        both spellings of "paid to us" must be searched."""
        list_paged.return_value = {"transactions": []}

        call_command("poll_qr_payments", "--limit", "10")

        receiver_aliases = {
            call.kwargs["receiver_alias"] for call in list_paged.call_args_list
        }
        self.assertEqual(receiver_aliases, {"+25761000000", "100200300"})

    @patch("apps.gateway.management.commands.poll_qr_payments.client.list_transactions_paged")
    def test_same_transaction_seen_under_both_receivers_is_matched_once(self, list_paged):
        """The same trxRef can surface under both the alias search and the
        account-number search — it must dedupe to a single match, not be
        rejected as ambiguous."""
        list_paged.return_value = {
            "transactions": [
                {
                    "trxRef": "IPS-QR-DUP", "status": "COMPLETED", "amount": "5000.00",
                    "isQrPayment": True, "provider": {},
                }
            ]
        }

        call_command("poll_qr_payments", "--limit", "10")

        self.watch.refresh_from_db()
        self.assertEqual(self.watch.status, QRPaymentWatch.Status.MATCHED)
        self.assertEqual(self.watch.matched_trx_ref, "IPS-QR-DUP")


class QRPayerIdentityResolutionTests(TestCase):
    """Once a QR payment completes, AmatoPay learns the payer's alias from
    the gateway's transaction lookup (``debtorAlias``) and verifies it the
    same way the alias-push flow verifies its payer upfront — so a QR
    Payment ends up just as complete a record."""

    databases = {"default", "security"}

    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-QR-4", legal_name="Shop Co", display_name="Shop Co",
            status=Merchant.Status.ACTIVE, qr_payments_enabled=True,
        )
        FiduciaryAccount.objects.create(
            account_number="FID-QR-4", account_name="Fiduciary", currency="BIF",
            active=True, verified_at=timezone.now(),
        )
        self.session = PaymentSession.objects.create(
            merchant=self.merchant, order_number="QR-4", description="QR order",
            amount=Decimal("5000.00"), payment_method=PaymentSession.PaymentMethod.QR,
            expires_at=timezone.now() + timedelta(hours=1),
            status=PaymentSession.Status.AWAITING_PAYMENT,
        )
        self.payment = Payment.objects.create(
            session=self.session, merchant=self.merchant, amount=self.session.amount,
            status=Payment.Status.COLLECTION_PENDING, provider_reference="IPS-QR-9",
        )
        GatewayRequest.objects.create(
            rail=GatewayRequest.Rail.COLLECTION, request_id="AMP-QR-REQ-1",
            payment=self.payment, provider_reference="IPS-QR-9", status="processing",
        )

    @patch("apps.gateway.services.client.verify_alias")
    @patch("apps.gateway.services.client.get_collection_status")
    def test_completed_qr_payment_verifies_and_stores_discovered_payer(
        self, get_status, verify_alias
    ):
        get_status.return_value = {"status": "COMPLETED", "debtorAlias": "+25779001234"}
        verify_alias.return_value = {
            "found": True,
            "status": "ACTIVE",
            "customer": {"name": "Jane Payer", "reference": "cust-42"},
            "account": {"type": "MOBILE", "currency": "BIF"},
        }

        with self.captureOnCommitCallbacks(execute=True):
            recover_collection_status(self.payment.collection)

        self.payment.refresh_from_db()
        verify_alias.assert_called_once()
        self.assertEqual(verify_alias.call_args.args[0]["alias"], "+25779001234")
        self.assertEqual(self.payment.payer_alias, "+25779001234")
        self.assertEqual(self.payment.payer_alias_type, "MOBILE")
        self.assertEqual(self.payment.payer_display_name, "Jane Payer")
        self.assertEqual(self.payment.payer_reference, "cust-42")

        verification = self.session.alias_verifications.get()
        self.assertEqual(verification.alias_value, "+25779001234")

    @patch("apps.gateway.services.client.verify_alias")
    @patch("apps.gateway.services.client.get_collection_status")
    def test_unverifiable_debtor_alias_does_not_block_completion(
        self, get_status, verify_alias
    ):
        get_status.return_value = {"status": "COMPLETED", "debtorAlias": "+25779009999"}
        verify_alias.return_value = {"found": False}

        with self.captureOnCommitCallbacks(execute=True):
            recover_collection_status(self.payment.collection)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.DELIVERY_PENDING)
        self.assertEqual(self.payment.payer_alias, "")

    @patch("apps.gateway.services.client.verify_alias")
    @patch("apps.gateway.services.client.get_collection_status")
    def test_no_debtor_alias_returned_leaves_payer_fields_blank(
        self, get_status, verify_alias
    ):
        get_status.return_value = {"status": "COMPLETED"}

        with self.captureOnCommitCallbacks(execute=True):
            recover_collection_status(self.payment.collection)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.DELIVERY_PENDING)
        self.assertEqual(self.payment.payer_alias, "")
        verify_alias.assert_not_called()

    @patch("apps.gateway.services.client.verify_alias")
    @patch("apps.gateway.services.client.get_collection_status")
    def test_alias_flow_payment_is_never_touched_even_if_debtor_alias_present(
        self, get_status, verify_alias
    ):
        """Guard is keyed on payer_alias already being blank — an
        alias-push payment (payer known from the start) must never be
        overwritten, even in a hypothetical response carrying debtorAlias."""
        self.payment.payer_alias = "+25761111111"
        self.payment.payer_alias_type = "MOBILE"
        self.payment.payer_display_name = "Original Payer"
        self.payment.save()
        get_status.return_value = {"status": "COMPLETED", "debtorAlias": "+25779009999"}

        with self.captureOnCommitCallbacks(execute=True):
            recover_collection_status(self.payment.collection)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payer_alias, "+25761111111")
        self.assertEqual(self.payment.payer_display_name, "Original Payer")
        verify_alias.assert_not_called()


class QRCheckoutApiGatewayOutageTests(TestCase):
    """AmatoPay decides the response — a MobileCashGatewayError carries the
    gateway's raw HTTP body in its message, which must never reach the
    merchant, on this endpoint either."""

    url = "/api/v1/checkout/qr-sessions/"

    def setUp(self):
        PricingPlan.objects.create(
            code="pay-as-you-go", name="Pay-as-you-go", currency="BIF",
            active=True, transaction_fee_percentage=Decimal("5"),
        )
        merchant = Merchant.objects.create(
            merchant_code="AMP-QR-API-1", legal_name="QR Api Co", display_name="QR Api Co",
            status=Merchant.Status.ACTIVE, qr_payments_enabled=True,
        )
        _, self.raw_key = MerchantApiKey.issue(merchant, "QR checkout API")
        self.client = APIClient()
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        self.payload = {
            "order_number": "QR-API-1", "description": "QR order",
            "amount": "5000.00", "currency": "BIF", "payer_alias": "+25779000000",
        }

    @patch("apps.gateway.services.client.verify_alias")
    def test_gateway_outage_returns_clean_message_not_raw_body(self, verify_alias):
        verify_alias.side_effect = MobileCashGatewayError(
            "alias.verify", 502, "<html>internal stack trace, db host, secrets</html>"
        )

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("internal stack trace", response.content.decode())
        self.assertNotIn("db host", response.content.decode())
        self.assertIn("temporarily unavailable", response.content.decode())
        self.assertFalse(PaymentSession.objects.exists())
