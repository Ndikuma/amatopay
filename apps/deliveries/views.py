from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey

from .models import Delivery, DeliveryConfirmation
from .serializers import (
    DeliveryConfirmationSerializer,
    DeliverySerializer,
    SecureDeliveryConfirmationSerializer,
)
from .services import confirm_delivery_with_code


class DeliveryViewSet(viewsets.ModelViewSet):
    queryset = Delivery.objects.none()
    serializer_class = DeliverySerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]

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
