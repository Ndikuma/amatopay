from rest_framework import serializers

from .models import (
    Delivery,
    DeliveryConfirmation,
    ProtectionClaim,
    ProtectionClaimEvidence,
)


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


class ProtectionClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtectionClaim
        fields = "__all__"
        read_only_fields = [
            "id",
            "status",
            "opened_by",
            "resolution",
            "resolved_at",
            "created_at",
            "updated_at",
        ]


class ProtectionClaimEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtectionClaimEvidence
        fields = "__all__"
        read_only_fields = ["id", "submitted_by", "created_at", "updated_at"]
