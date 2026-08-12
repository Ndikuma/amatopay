from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_view
from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey
from .models import PaymentSession
from .serializers import PaymentSessionSerializer


@extend_schema_view(
    create=extend_schema(
        summary="Create a protected payment session",
        description=(
            "Accepts and verifies the payer MOBILE alias, records the resolved customer name, "
            "creates the checkout/payment fee snapshot, and initiates RTP using "
            "AmatoPay's creditor alias. The session expires after three hours; merchants "
            "do not submit an expiry or create RTP separately."
        ),
        examples=[
            OpenApiExample(
                "Create protected BIF payment",
                request_only=True,
                value={
                    "order_number": "ORDER-1001",
                    "description": "Protected online purchase",
                    "amount": "100000.00",
                    "currency": "BIF",
                    "payer_alias": "+25779000000",
                    "return_url": "https://merchant.bi/payment/result",
                },
            )
        ],
    )
)
class PaymentSessionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    GenericViewSet,
):
    queryset = PaymentSession.objects.none()
    serializer_class = PaymentSessionSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]
    lookup_field = "session_id"

    def get_queryset(self):
        return PaymentSession.objects.filter(merchant=self.request.merchant).order_by(
            "-created_at"
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        session = self.get_object()
        if session.status not in {
            PaymentSession.Status.CREATED,
            PaymentSession.Status.AWAITING_ALIAS,
            PaymentSession.Status.ALIAS_VERIFIED,
        }:
            raise ValidationError("This payment session can no longer be cancelled.")
        session.status = PaymentSession.Status.CANCELLED
        session.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(session).data)
