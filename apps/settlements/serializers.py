from rest_framework import serializers
from .models import Settlement, SettlementBatch


class SettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settlement
        fields = "__all__"
        read_only_fields = [
            "id",
            "reference",
            "provider_reference",
            "beneficiary_alias",
            "status",
            "completed_at",
            "failure_code",
            "created_at",
            "updated_at",
        ]


class SettlementBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = SettlementBatch
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
