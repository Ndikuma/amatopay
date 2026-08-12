from rest_framework import serializers
from .forms import ACCEPTANCE_PROOF_CHOICES
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


class DeliveryReviewRequestSerializer(serializers.Serializer):
    secure_code = serializers.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        required=False,
        allow_blank=True,
        write_only=True,
    )
    payer_alias = serializers.CharField(max_length=160, required=False, allow_blank=True)
    proof_method = serializers.ChoiceField(choices=ACCEPTANCE_PROOF_CHOICES)
    description = serializers.CharField(max_length=2000)

    def validate(self, attrs):
        if not attrs.get("secure_code") and not attrs.get("payer_alias", "").strip():
            raise serializers.ValidationError(
                "Enter either the delivery code or the payer alias used for payment."
            )
        return attrs
