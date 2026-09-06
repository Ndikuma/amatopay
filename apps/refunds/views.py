from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import IsActiveMerchant
from apps.payments.models import Payment

from .models import Refund
from .serializers import RefundSerializer


class RefundViewSet(viewsets.ModelViewSet):
    queryset = Refund.objects.none()
    serializer_class = RefundSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [IsActiveMerchant]

    def get_queryset(self):
        return Refund.objects.filter(payment__merchant=self.request.merchant).order_by(
            "-created_at"
        )

    def perform_create(self, serializer):
        payment = serializer.validated_data["payment"]
        if payment.merchant_id != self.request.merchant.id:
            raise ValidationError({"payment": "Payment does not belong to this merchant."})
        if payment.status not in {
            Payment.Status.PAID,
            Payment.Status.FUNDS_HELD,
            Payment.Status.DELIVERY_PENDING,
        }:
            raise ValidationError({"payment": "Payment is not eligible for a refund."})
        serializer.save(requested_by=f"merchant:{self.request.api_key.prefix}")
