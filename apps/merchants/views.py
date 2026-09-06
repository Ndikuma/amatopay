from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.utils import timezone
from .models import (
    Merchant,
    MerchantKYB,
    MerchantDocument,
    MerchantSettlementAccount,
)
from .serializers import (
    MerchantSerializer,
    MerchantKYBSerializer,
    MerchantDocumentSerializer,
    MerchantSettlementAccountSerializer,
)
from .services import activation_status
from apps.gateway import client as rail_client
from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey, IsOperationsUser


class MerchantPingView(APIView):
    """Merchant-facing health check and onboarding status.

    Use it to confirm your API key works and to see whether your account is
    verified and cleared to operate with AmatoPay.
    """

    # Same API key as every other endpoint (Bearer or X-Api-Key). Uses
    # HasMerchantApiKey (not IsActiveMerchant) so a merchant still in review
    # can call it to see what is left to activate.
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]

    @extend_schema(
        summary="Ping AmatoPay and read your merchant activation status",
        responses={200: dict},
    )
    def get(self, request):
        merchant = request.merchant
        status = activation_status(merchant)
        if status["can_operate"]:
            message = (
                f"Welcome to AmatoPay, {merchant.display_name}. "
                "Your account is verified — you can start accepting payments."
            )
        else:
            message = (
                f"Welcome, {merchant.display_name}. Your account is still in "
                "review; some verification steps are pending."
            )
        return Response(
            {
                "message": message,
                "merchant": {
                    "code": merchant.merchant_code,
                    "display_name": merchant.display_name,
                    "status": merchant.status,
                    "country": merchant.country,
                    "default_currency": merchant.default_currency,
                },
                "can_operate": status["can_operate"],
                "verification": {
                    "readiness": status["readiness"],
                    "completed": status["completed"],
                    "total": status["total"],
                    "checks": status["checks"],
                    "pending": [
                        {"key": key, "label": status["labels"][key]}
                        for key in status["pending"]
                    ],
                },
                "api_key_prefix": getattr(request.api_key, "prefix", ""),
                "server_time": timezone.now().isoformat(),
            }
        )


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

