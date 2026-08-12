from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import (
    Merchant,
    MerchantKYB,
    MerchantDocument,
    BeneficialOwner,
    MerchantSettlementAccount,
)
from .serializers import (
    MerchantSerializer,
    MerchantKYBSerializer,
    MerchantDocumentSerializer,
    BeneficialOwnerSerializer,
    MerchantSettlementAccountSerializer,
)
from apps.gateway import client as rail_client
from apps.developers.permissions import IsOperationsUser


class OperationsModelViewSet(ModelViewSet):
    permission_classes = [IsOperationsUser]


class MerchantViewSet(OperationsModelViewSet):
    queryset = Merchant.objects.all().order_by("-created_at")
    serializer_class = MerchantSerializer
    filterset_fields = ["status"]
    search_fields = ["merchant_code", "legal_name", "display_name"]


class MerchantKYBViewSet(OperationsModelViewSet):
    queryset = MerchantKYB.objects.select_related("merchant").all()
    serializer_class = MerchantKYBSerializer
    filterset_fields = ["merchant", "decision", "verified"]


class MerchantDocumentViewSet(OperationsModelViewSet):
    queryset = MerchantDocument.objects.select_related("merchant").all()
    serializer_class = MerchantDocumentSerializer
    filterset_fields = ["merchant", "document_type", "verified"]


class BeneficialOwnerViewSet(OperationsModelViewSet):
    queryset = BeneficialOwner.objects.select_related("merchant").all()
    serializer_class = BeneficialOwnerSerializer
    filterset_fields = ["merchant", "pep", "sanctions_match"]


class MerchantSettlementAccountViewSet(OperationsModelViewSet):
    queryset = MerchantSettlementAccount.objects.select_related("merchant").all()
    serializer_class = MerchantSettlementAccountSerializer
    filterset_fields = ["merchant", "verification_status", "is_primary", "is_active"]

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        account = self.get_object()
        payload = {
            "requestId": f"AMP-MER-ALIAS-{account.id.hex[:16].upper()}",
            "alias": account.alias_value,
            "aliasType": account.alias_type,
        }
        result = rail_client.verify_alias(payload)
        customer = result.get("customer") or {}
        acct = result.get("account") or {}
        found = bool(result.get("found", result.get("valid", False)))
        active = str(result.get("status", "")).upper() == "ACTIVE"
        account.raw_verification = result
        if found and active:
            account.verification_status = (
                MerchantSettlementAccount.Verification.VERIFIED
            )
            account.account_name = customer.get(
                "name", customer.get("display_name", "")
            )
            account.provider_customer_reference = customer.get("reference", "")
            account.account_type = acct.get("type", acct.get("account_type", ""))
            account.currency = acct.get("currency", account.currency)
            account.verified_at = timezone.now()
        else:
            account.verification_status = MerchantSettlementAccount.Verification.FAILED
        account.save()
        return Response(self.get_serializer(account).data)
