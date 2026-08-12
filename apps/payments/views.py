from rest_framework.decorators import action
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet
from drf_spectacular.utils import extend_schema, inline_serializer

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey
from apps.deliveries.serializers import (
    DeliveryReviewRequestSerializer,
    SecureDeliveryConfirmationSerializer,
)
from apps.deliveries.services import confirm_delivery_with_code, request_delivery_review

from .models import Payment
from .serializers import PaymentSerializer


class PaymentViewSet(ReadOnlyModelViewSet):
    queryset = Payment.objects.none()
    serializer_class = PaymentSerializer
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]
    lookup_field = "reference"
    filterset_fields = ["status", "currency"]
    search_fields = ["reference", "session__order_number"]
    ordering_fields = ["created_at", "amount", "paid_at"]

    def get_queryset(self):
        return (
            Payment.objects.filter(merchant=self.request.merchant)
            .select_related("session")
            .prefetch_related("history")
            .order_by("-created_at")
        )

    @extend_schema(
        summary="Confirm delivery with the payer's secure code",
        description=(
            "The payment reference is taken from the URL. The JSON body contains "
            "only the payer's six-digit secure delivery code."
        ),
        request=SecureDeliveryConfirmationSerializer,
        responses={
            200: inline_serializer(
                name="DeliveryConfirmationResult",
                fields={
                    "payment_reference": serializers.CharField(),
                    "delivery_confirmed": serializers.BooleanField(),
                    "confirmation_id": serializers.UUIDField(),
                    "status": serializers.CharField(),
                },
            ),
            201: inline_serializer(
                name="DeliveryConfirmationCreatedResult",
                fields={
                    "payment_reference": serializers.CharField(),
                    "delivery_confirmed": serializers.BooleanField(),
                    "confirmation_id": serializers.UUIDField(),
                    "status": serializers.CharField(),
                },
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="confirm-delivery")
    def confirm_delivery(self, request, reference=None):
        serializer = SecureDeliveryConfirmationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        confirmation, created = confirm_delivery_with_code(
            self.get_object(), serializer.validated_data["secure_code"]
        )
        payment = self.get_object()
        return Response(
            {
                "payment_reference": payment.reference,
                "delivery_confirmed": True,
                "confirmation_id": confirmation.id,
                "status": payment.status,
            },
            status=201 if created else 200,
        )

    @extend_schema(
        summary="Open a manual delivery proof review",
        description=(
            "Use when the payer received delivery but cannot verify with the "
            "six-digit code. This freezes funds and opens AmatoPay review; it "
            "does not release funds automatically."
        ),
        request=DeliveryReviewRequestSerializer,
        responses={
            201: inline_serializer(
                name="DeliveryReviewRequestResult",
                fields={
                    "payment_reference": serializers.CharField(),
                    "review_opened": serializers.BooleanField(),
                    "claim_id": serializers.UUIDField(),
                    "status": serializers.CharField(),
                },
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="delivery-review")
    def delivery_review(self, request, reference=None):
        serializer = DeliveryReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        claim, created = request_delivery_review(
            self.get_object(),
            serializer.validated_data.get("secure_code"),
            payer_alias=serializer.validated_data.get("payer_alias", ""),
            reason=f"alternative_proof:{serializer.validated_data['proof_method']}",
            description=serializer.validated_data["description"].strip(),
        )
        payment = self.get_object()
        return Response(
            {
                "payment_reference": payment.reference,
                "review_opened": True,
                "claim_id": claim.id,
                "status": payment.status,
            },
            status=201 if created else 200,
        )
