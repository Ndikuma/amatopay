from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.gateway.models import GatewayTransactionPoll
from apps.gateway.services import _poll_transaction


class FakeGatewayRequest:
    objects = Mock()

    def __init__(self):
        self.pk = "request-pk"
        self.request_id = "AMP-COLL-1"
        self.provider_reference = "TRX-1001"
        self.status = "pending"
        self.consecutive_poll_failures = 0

    @property
    def trx_ref(self):
        return self.provider_reference


class GatewayTransactionMonitorTests(SimpleTestCase):
    def setUp(self):
        FakeGatewayRequest.objects.reset_mock()
        self.record = FakeGatewayRequest()

    @patch("apps.gateway.services.GatewayTransactionPoll.objects.create")
    def test_poll_uses_persisted_trx_ref_and_audits_result(self, create_poll):
        getter = Mock(return_value={"trxRef": "TRX-1001", "status": "COMPLETED"})

        result = _poll_transaction(
            self.record, GatewayTransactionPoll.Rail.COLLECTION, getter
        )

        getter.assert_called_once_with("TRX-1001")
        self.assertEqual(result["status"], "COMPLETED")
        FakeGatewayRequest.objects.filter.assert_called_once_with(pk="request-pk")
        self.assertTrue(create_poll.call_args.kwargs["succeeded"])
        self.assertEqual(create_poll.call_args.kwargs["trx_ref"], "TRX-1001")

    @patch("apps.gateway.services.GatewayTransactionPoll.objects.create")
    def test_failed_poll_records_error_and_schedules_backoff(self, create_poll):
        error = RuntimeError("gateway temporarily unavailable")
        getter = Mock(side_effect=error)

        with self.assertRaises(RuntimeError):
            _poll_transaction(
                self.record, GatewayTransactionPoll.Rail.COLLECTION, getter
            )

        update = FakeGatewayRequest.objects.filter.return_value.update
        self.assertEqual(update.call_args.kwargs["consecutive_poll_failures"], 1)
        self.assertIn("temporarily unavailable", update.call_args.kwargs["last_poll_error"])
        self.assertFalse(create_poll.call_args.kwargs["succeeded"])
