from django.test import TestCase

from apps.merchants.models import Merchant, MerchantSettlementAccount
from apps.merchants.serializers import MerchantSettlementAccountSerializer


class MerchantSettlementAccountSerializerTests(TestCase):
    """AmatoPay decides what to expose — the gateway's raw alias-verify
    response must never round-trip through the API, even to operations
    staff."""

    def test_raw_verification_is_never_serialized(self):
        merchant = Merchant.objects.create(
            merchant_code="AMP-SETTLE-1", legal_name="Settle Co",
            display_name="Settle Co", status=Merchant.Status.ACTIVE,
        )
        account = MerchantSettlementAccount.objects.create(
            merchant=merchant, alias_value="+25761000000",
            raw_verification={"secret": "gateway-internal-detail"},
        )

        data = MerchantSettlementAccountSerializer(account).data

        self.assertNotIn("raw_verification", data)
        self.assertEqual(data["alias_value"], "+25761000000")
