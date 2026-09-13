from django.test import TestCase

from apps.fiduciary.models import FiduciaryAccount
from apps.fiduciary.serializers import FiduciaryAccountSerializer


class FiduciaryAccountSerializerTests(TestCase):
    """AmatoPay decides what to expose — the gateway's raw alias-verify
    response must never round-trip through the API, even to operations
    staff."""

    def test_raw_verification_is_never_serialized(self):
        account = FiduciaryAccount.objects.create(
            creditor_alias="+25761000000",
            account_number="100200300",
            account_name="AmatoPay Fiduciary",
            raw_verification={"secret": "gateway-internal-detail"},
        )

        data = FiduciaryAccountSerializer(account).data

        self.assertNotIn("raw_verification", data)
        self.assertEqual(data["creditor_alias"], "+25761000000")
