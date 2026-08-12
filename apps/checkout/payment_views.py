import hmac
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.checkout.models import PaymentSession
from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey
from apps.gateway.services import AliasNotPayableError, verify_merchant_payer_alias
from .alias_serializers import (
    MerchantAliasVerificationResultSerializer,
    MerchantAliasVerificationSerializer,
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
@permission_classes([HasMerchantApiKey])
def merchant_alias_verify(request):
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
    s = get_object_or_404(
        PaymentSession.objects.select_related("merchant"), session_id=session_id
    )
    if not hmac.compare_digest(s.client_secret, client_secret):
        raise PermissionDenied("Invalid checkout client secret.")
    if s.expires_at <= timezone.now():
        if s.status not in {
            PaymentSession.Status.COMPLETED,
            PaymentSession.Status.CANCELLED,
            PaymentSession.Status.EXPIRED,
        }:
            s.status = PaymentSession.Status.EXPIRED
            s.save(update_fields=["status", "updated_at"])
        raise ValidationError("This payment session has expired.")
    if s.status == PaymentSession.Status.CANCELLED:
        raise ValidationError("This payment session was cancelled.")
    return s


@extend_schema(
    summary="Get hosted checkout payment status",
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
    client_secret = request.query_params.get("client_secret", "")
    session = _session(session_id, client_secret)
    try:
        payment = session.payment
    except ObjectDoesNotExist:
        payment = None
    payment_reference = payment.reference if payment else ""
    payment_status = payment.status if payment else session.status
    terminal = payment_status in {
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
    return Response(
        {
            "session_id": str(session.session_id),
            "session_status": session.status,
            "payment_reference": payment_reference,
            "payment_status": payment_status,
            "terminal": terminal,
            "return_url": session.return_url,
        }
    )
