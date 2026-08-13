from rest_framework import serializers
from .models import Delivery, DeliveryConfirmation


class DeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = Delivery
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class DeliveryConfirmationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryConfirmation
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class SecureDeliveryConfirmationSerializer(serializers.Serializer):
    """The payment reference is supplied by the endpoint URL."""

    secure_code = serializers.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        write_only=True,
    )
