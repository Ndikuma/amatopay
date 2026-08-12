from rest_framework import serializers
from .models import FiduciaryAccount, FundHold, FiduciaryEntry


class FiduciaryAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiduciaryAccount
        fields = "__all__"


class FundHoldSerializer(serializers.ModelSerializer):
    class Meta:
        model = FundHold
        fields = "__all__"


class FiduciaryEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = FiduciaryEntry
        fields = "__all__"
