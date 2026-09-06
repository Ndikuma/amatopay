import hmac

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import IsActiveMerchant
from apps.gateway.services import AliasNotPayableError, verify_merchant_payer_alias

from .models import PaymentSession
from .serializers import (
    MerchantAliasVerificationResultSerializer,
    MerchantAliasVerificationSerializer,
    PaymentSessionSerializer,
)


@extend_schema_view(
    create=extend_schema(
        summary="Create a protected payment session",
        description=(
            "Accepts and verifies the payer MOBILE alias, records the resolved customer name, "
            "creates the checkout/payment fee snapshot, and initiates a collection using "
            "AmatoPay's creditor alias. The session expires after three hours; merchants "
            "do not submit an expiry or create a collection separately."
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
    permission_classes = [IsActiveMerchant]
    lookup_field = "session_id"

    def get_queryset(self):
        return PaymentSession.objects.filter(merchant=self.request.merchant).order_by(
            "-created_at"
        )


@extend_schema(
    summary="Verify a payer MOBILE alias",
    description="Look up an active MOBILE payer alias and return its registered customer name.",
    parameters=[OpenApiParameter("payer_alias", str, OpenApiParameter.QUERY, required=True)],
    request=None,
    responses={200: MerchantAliasVerificationResultSerializer},
)
@api_view(["GET"])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([IsActiveMerchant])
def merchant_alias_verify(request):
    """Verify a payer's MOBILE alias for the authenticated merchant."""
    serializer = MerchantAliasVerificationSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    try:
        verification = verify_merchant_payer_alias(
            merchant=request.merchant,
            payer_alias=serializer.validated_data["payer_alias"],
        )
    except AliasNotPayableError as exc:
        raise ValidationError({"payer_alias": str(exc)}) from exc

    return Response(
        {
            "alias_type": "MOBILE",
            "payer_alias": verification.alias_value,
            "found": verification.found,
            "status": verification.status,
            "customer_full_name": verification.display_name,
            "currency": verification.currency,
        }
    )


def _session(session_id, client_secret):
    """Validate the client secret and return a live (non-expired) payment session."""
    session = get_object_or_404(
        PaymentSession.objects.select_related("merchant"), session_id=session_id
    )

    if not hmac.compare_digest(session.client_secret, client_secret):
        raise PermissionDenied("Invalid checkout client secret.")

    if session.expires_at <= timezone.now():
        if session.status not in {
            PaymentSession.Status.COMPLETED,
            PaymentSession.Status.CANCELLED,
            PaymentSession.Status.EXPIRED,
        }:
            session.status = PaymentSession.Status.EXPIRED
            session.save(update_fields=["status", "updated_at"])
        raise ValidationError("This payment session has expired.")

    if session.status == PaymentSession.Status.CANCELLED:
        raise ValidationError("This payment session was cancelled.")

    return session


TERMINAL_PAYMENT_STATES = {
    "paid",
    "funds_held",
    "delivery_pending",
    "settled",
    "failed",
    "rejected",
    "cancelled",
    "expired",
    "refunded",
}


@extend_schema(
    summary="Get hosted checkout payment status",
    description="Retrieve the current status of a checkout session including payment details and terminal state.",
    parameters=[OpenApiParameter("client_secret", str, OpenApiParameter.QUERY, required=True)],
    responses=inline_serializer(
        name="CheckoutStatus",
        fields={
            "session_id": serializers.UUIDField(),
            "session_status": serializers.CharField(),
            "payment_reference": serializers.CharField(),
            "payment_status": serializers.CharField(),
            "terminal": serializers.BooleanField(),
            "return_url": serializers.URLField(allow_blank=True),
        },
    ),
)
@api_view(["GET"])
@permission_classes([AllowAny])
def checkout_status(request, session_id):
    """Return the current status of a hosted checkout payment session."""
    client_secret = request.query_params.get("client_secret", "")
    session = _session(session_id, client_secret)

    try:
        payment = session.payment
    except ObjectDoesNotExist:
        payment = None

    payment_reference = payment.reference if payment else ""
    payment_status = payment.status if payment else session.status

    return Response(
        {
            "session_id": str(session.session_id),
            "session_status": session.status,
            "payment_reference": payment_reference,
            "payment_status": payment_status,
            "terminal": payment_status in TERMINAL_PAYMENT_STATES,
            "return_url": session.return_url,
        }
    )
