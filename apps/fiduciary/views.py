from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey, IsOperationsUser

from .models import FiduciaryAccount, FiduciaryEntry, FundHold
from .serializers import (
    FiduciaryAccountSerializer,
    FiduciaryEntrySerializer,
    FundHoldSerializer,
)


class FiduciaryAccountViewSet(ModelViewSet):
    queryset = FiduciaryAccount.objects.all()
    serializer_class = FiduciaryAccountSerializer
    permission_classes = [IsOperationsUser]


class FundHoldViewSet(ReadOnlyModelViewSet):
    queryset = FundHold.objects.none()
    serializer_class = FundHoldSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]
    filterset_fields = ["status", "payment"]

    def get_queryset(self):
        return (
            FundHold.objects.filter(payment__merchant=self.request.merchant)
            .select_related("payment", "fiduciary_account")
            .order_by("-held_at")
        )


class FiduciaryEntryViewSet(ReadOnlyModelViewSet):
    queryset = FiduciaryEntry.objects.none()
    serializer_class = FiduciaryEntrySerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]

    def get_queryset(self):
        return FiduciaryEntry.objects.filter(
            payment__merchant=self.request.merchant
        ).order_by("-created_at")
