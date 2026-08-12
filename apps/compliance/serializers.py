from rest_framework import serializers
from .models import (
    SuspiciousTransaction,
    RegulatoryReport,
    DataRetentionRecord,
)


class SuspiciousTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuspiciousTransaction
        fields = "__all__"


class RegulatoryReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegulatoryReport
        fields = "__all__"


class DataRetentionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataRetentionRecord
        fields = "__all__"
