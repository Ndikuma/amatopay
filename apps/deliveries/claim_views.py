from django.db import transaction
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey
from apps.fiduciary.models import FundHold
from apps.payments.models import Payment

from .claim_serializers import (
    ProtectionClaimEvidenceSerializer,
    ProtectionClaimSerializer,
)
from .models import ProtectionClaim, ProtectionClaimEvidence


class ProtectionClaimViewSet(viewsets.ModelViewSet):
    queryset = ProtectionClaim.objects.none()
    serializer_class = ProtectionClaimSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]

    def get_queryset(self):
        return ProtectionClaim.objects.filter(
            payment__merchant=self.request.merchant
        ).order_by("-created_at")

    @transaction.atomic
    def perform_create(self, serializer):
        payment = serializer.validated_data["payment"]
        if payment.merchant_id != self.request.merchant.id:
            raise ValidationError({"payment": "Payment does not belong to this merchant."})
        claim = serializer.save(opened_by=f"merchant:{self.request.api_key.prefix}")
        payment.status = Payment.Status.DISPUTED
        payment.save(update_fields=["status", "updated_at"])
        if hasattr(payment, "fund_hold"):
            payment.fund_hold.status = FundHold.Status.DISPUTED
            payment.fund_hold.save(update_fields=["status", "updated_at"])
        return claim


class ProtectionClaimEvidenceViewSet(viewsets.ModelViewSet):
    queryset = ProtectionClaimEvidence.objects.none()
    serializer_class = ProtectionClaimEvidenceSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]

    def get_queryset(self):
        return ProtectionClaimEvidence.objects.filter(
            claim__payment__merchant=self.request.merchant
        ).order_by("-created_at")

    def perform_create(self, serializer):
        claim = serializer.validated_data["claim"]
        if claim.payment.merchant_id != self.request.merchant.id:
            raise ValidationError({"claim": "Claim does not belong to this merchant."})
        serializer.save(submitted_by=f"merchant:{self.request.api_key.prefix}")
