from rest_framework import serializers
from .models import Refund


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = "__all__"
        read_only_fields = [
            "id",
            "status",
            "requested_by",
            "provider_reference",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        payment = attrs.get("payment")
        amount = attrs.get("amount")
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be positive."})
        if payment and amount and amount > payment.amount:
            raise serializers.ValidationError(
                {"amount": "Refund cannot exceed the payment amount."}
            )
        return attrs
