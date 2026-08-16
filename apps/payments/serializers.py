from rest_framework import serializers
from .models import Payment, PaymentStatusHistory


class PaymentHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentStatusHistory
        fields = ["status", "reason", "source", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    total_amount = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True
    )
    net_amount = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True
    )
    history = PaymentHistorySerializer(many=True, read_only=True)

   
    class Meta:
        model = Payment
        fields = [
            "reference",
            "status",
            "amount",
            "fee_amount",
            "fee_percentage",
            "net_amount",
            "fee_source",
            "total_amount",
            "currency",
            "paid_at",
            "failure_code",
            "failure_message",
            "metadata",
            "created_at",
            "history",
        ]
