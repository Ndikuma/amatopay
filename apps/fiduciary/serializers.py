from rest_framework import serializers
from .models import FiduciaryAccount, FundHold, FiduciaryEntry


class FiduciaryAccountSerializer(serializers.ModelSerializer):
    """AmatoPay decides what to expose — raw_verification (the gateway's
    full alias-verify response) stays internal, never round-tripped through
    the API even for operations staff."""

    class Meta:
        model = FiduciaryAccount
        exclude = ["raw_verification"]


class FundHoldSerializer(serializers.ModelSerializer):
    class Meta:
        model = FundHold
        fields = "__all__"


class FiduciaryEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = FiduciaryEntry
        fields = "__all__"
