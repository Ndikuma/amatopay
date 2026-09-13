from rest_framework import serializers
from .models import (
    Merchant,
    MerchantKYB,
    MerchantDocument,
    MerchantSettlementAccount,
)


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class MerchantKYBSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantKYB
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class MerchantDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantDocument
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class MerchantSettlementAccountSerializer(serializers.ModelSerializer):
    """AmatoPay decides what to expose — raw_verification (the gateway's
    full alias-verify response) stays internal, never round-tripped through
    the API even for operations staff."""

    class Meta:
        model = MerchantSettlementAccount
        exclude = ["raw_verification"]
        read_only_fields = [
            "id",
            "verification_status",
            "verified_at",
            "account_name",
            "account_type",
            "provider_customer_reference",
            "created_at",
            "updated_at",
        ]
