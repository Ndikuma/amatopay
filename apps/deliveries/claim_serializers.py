from rest_framework import serializers

from .models import ProtectionClaim, ProtectionClaimEvidence


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
