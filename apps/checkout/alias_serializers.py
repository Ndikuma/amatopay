from rest_framework import serializers


class MerchantAliasVerificationSerializer(serializers.Serializer):
    payer_alias = serializers.CharField(max_length=160, trim_whitespace=True)


class MerchantAliasVerificationResultSerializer(serializers.Serializer):
    alias_type = serializers.CharField()
    payer_alias = serializers.CharField()
    found = serializers.BooleanField()
    status = serializers.CharField()
    customer_full_name = serializers.CharField()
    currency = serializers.CharField()
