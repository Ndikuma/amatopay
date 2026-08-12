from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.gateway.provider import MobileCashGateway, MobileCashGatewayError


def response(status_code, payload):
    result = Mock()
    result.ok = 200 <= status_code < 300
    result.status_code = status_code
    result.json.return_value = payload
    result.text = str(payload)
    result.content = b"json"
    return result


class MobileCashGatewayTests(SimpleTestCase):
    def setUp(self):
        self.gateway = MobileCashGateway(
            base_url="https://mobilecash.example",
            username="user",
            password="password",
            creditor_alias="+25761000000",
        )
        self.gateway._session = Mock()
        self.gateway._token = "jwt"
        self.gateway._token_expires_at = 9_999_999_999

    def test_alias_response_is_normalized_for_amatopay(self):
        self.gateway._session.request.return_value = response(
            200,
            {
                "isVerified": True,
                "canDebit": True,
                "fullName": "Customer Name",
                "rowid": 42,
                "defaultAccount": "100200300",
                "accountType": "CURRENT",
                "servicerCode": "CECFBI",
                "servicerCodeType": "BIC",
                "currency": "BIF",
            },
        )

        result = self.gateway.verify_alias("+25779000000")

        self.assertTrue(result["found"])
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["customer"]["name"], "Customer Name")
        self.assertEqual(result["account"]["number"], "100200300")
        self.assertEqual(result["account"]["account_type"], "CURRENT")
        self.assertEqual(result["account"]["servicer_code"], "CECFBI")

    def test_rtp_uses_total_amount_and_normalizes_reference(self):
        self.gateway._session.request.return_value = response(
            200,
            {
                "rowid": 1,
                "trxRef": "IPS-123",
                "payerAlias": "+25779000000",
                "receiverAlias": "+25761000000",
                "amount": 1050,
                "status": "pending",
                "statusDescription": "Awaiting payer approval",
            },
        )
        payload = {
            "requestId": "AMP-RTP-1",
            "payerAlias": "+25779000000",
            "amount": "1000.00",
            "totalAmount": "1050.00",
            "order": {"description": "Order 1"},
        }

        result = self.gateway.create_rtp(payload)

        self.assertEqual(result["trxRef"], "IPS-123")
        request = self.gateway._session.request.call_args
        self.assertEqual(request.kwargs["json"]["amount"], 1050.0)

    def test_provider_statuses_are_normalized(self):
        self.assertEqual(self.gateway.normalize_status("successful"), "COMPLETED")
        self.assertEqual(self.gateway.normalize_status("declined"), "REJECTED")
        self.assertEqual(self.gateway.normalize_status("approved"), "PROCESSING")

    def test_p2p_uses_fiduciary_alias_and_exact_mobilecash_contract(self):
        self.gateway._session.request.return_value = response(
            200,
            {
                "transaction": {
                    "trxRef": "P2P-456",
                    "status": "processing",
                    "statusDescription": "Processing payout",
                },
                "trxRef": "P2P-456",
                "trackingEndpoint": "/transactions/P2P-456",
                "fees": 0,
                "totalAmount": 95000,
            },
        )
        result = self.gateway.create_p2p(
            {
                "requestId": "AMP-P2P-1",
                "settlementReference": "AMP-STL-1",
                "beneficiary": {"alias": "+25768000000"},
                "amount": "95000.00",
                "description": "AmatoPay merchant settlement AMP-STL-1",
            }
        )

        self.assertEqual(result["trxRef"], "P2P-456")
        request = self.gateway._session.request.call_args
        self.assertEqual(
            request.args[1], "https://mobilecash.example/api/MobileTrxPay/p2p"
        )
        self.assertEqual(
            request.kwargs["json"],
            {
                "payerAlias": "+25761000000",
                "receiverAlias": "+25768000000",
                "amount": 95000.0,
                "description": "AmatoPay merchant settlement AMP-STL-1",
            },
        )

    def test_p2p_rejects_fiduciary_alias_as_merchant_destination(self):
        with self.assertRaisesMessage(
            MobileCashGatewayError, "must differ from the AmatoPay fiduciary alias"
        ):
            self.gateway.create_p2p(
                {
                    "requestId": "AMP-P2P-INVALID",
                    "beneficiary": {
                        "aliasType": "MOBILE",
                        "alias": "+25761000000",
                    },
                    "amount": "95000.00",
                }
            )

        self.gateway._session.request.assert_not_called()

    def test_transaction_by_reference_uses_saved_trx_ref(self):
        self.gateway._session.request.return_value = response(
            200,
            {
                "transaction": {
                    "trxRef": "P2P-456",
                    "status": "successful",
                    "statusDescription": "Transaction completed",
                }
            },
        )

        result = self.gateway.get_transaction("P2P-456")

        self.assertEqual(result["trxRef"], "P2P-456")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["reasonCode"], "Transaction completed")
        request = self.gateway._session.request.call_args
        self.assertEqual(
            request.args[1],
            "https://mobilecash.example/api/MobileTrxPay/reference/P2P-456",
        )

    def test_create_rejects_response_without_trx_ref(self):
        self.gateway._session.request.return_value = response(
            200, {"status": "pending", "message": "Accepted without reference"}
        )

        with self.assertRaisesRegex(Exception, "did not contain trxRef"):
            self.gateway.create_rtp(
                {
                    "requestId": "AMP-RTP-MISSING",
                    "payerAlias": "+25779000000",
                    "amount": "1000.00",
                }
            )
