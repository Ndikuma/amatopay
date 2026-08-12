from rest_framework import viewsets

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey, IsOperationsUser

from .models import Settlement, SettlementBatch
from .serializers import SettlementBatchSerializer, SettlementSerializer


class SettlementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Settlement.objects.none()
    serializer_class = SettlementSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]
    filterset_fields = ["status", "reference"]

    def get_queryset(self):
        return (
            Settlement.objects.filter(merchant=self.request.merchant)
            .select_related("payment", "merchant")
            .order_by("-created_at")
        )


class SettlementBatchViewSet(viewsets.ModelViewSet):
    queryset = SettlementBatch.objects.all().order_by("-business_date")
    serializer_class = SettlementBatchSerializer
    permission_classes = [IsOperationsUser]
