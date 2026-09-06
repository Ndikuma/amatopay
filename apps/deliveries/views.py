from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import IsActiveMerchant
from apps.fiduciary.models import FundHold
from apps.payments.models import Payment

from .models import (
    Delivery,
    DeliveryConfirmation,
    ProtectionClaim,
    ProtectionClaimEvidence,
)
from .serializers import (
    DeliveryConfirmationSerializer,
    DeliverySerializer,
    ProtectionClaimEvidenceSerializer,
    ProtectionClaimSerializer,
    SecureDeliveryConfirmationSerializer,
)
from .services import confirm_delivery_with_code


class DeliveryViewSet(viewsets.ModelViewSet):
    queryset = Delivery.objects.none()
    serializer_class = DeliverySerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [IsActiveMerchant]

    def get_queryset(self):
        return (
            Delivery.objects.select_related("payment")
            .filter(payment__merchant=self.request.merchant)
            .order_by("-created_at")
        )

    @action(detail=True, methods=["post"])
    def mark_delivered(self, request, pk=None):
        d = self.get_object()
        d.status = Delivery.Status.DELIVERED
        d.delivered_at = timezone.now()
        d.evidence = request.data.get("evidence", d.evidence)
        d.save()
        return Response(DeliverySerializer(d).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        d = self.get_object()
        serializer = SecureDeliveryConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        c, _ = confirm_delivery_with_code(
            d.payment, serializer.validated_data["secure_code"]
        )
        return Response(DeliveryConfirmationSerializer(c).data)


class ProtectionClaimViewSet(viewsets.ModelViewSet):
    queryset = ProtectionClaim.objects.none()
    serializer_class = ProtectionClaimSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [IsActiveMerchant]

    def get_queryset(self):
        return ProtectionClaim.objects.filter(
            payment__merchant=self.request.merchant
        ).order_by("-created_at")

    @transaction.atomic
    def perform_create(self, serializer):
        payment = serializer.validated_data["payment"]
        if payment.merchant_id != self.request.merchant.id:
            raise ValidationError(
                {"payment": "Payment does not belong to this merchant."}
            )
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
    permission_classes = [IsActiveMerchant]

    def get_queryset(self):
        return ProtectionClaimEvidence.objects.filter(
            claim__payment__merchant=self.request.merchant
        ).order_by("-created_at")

    def perform_create(self, serializer):
        claim = serializer.validated_data["claim"]
        if claim.payment.merchant_id != self.request.merchant.id:
            raise ValidationError({"claim": "Claim does not belong to this merchant."})
        serializer.save(submitted_by=f"merchant:{self.request.api_key.prefix}")
