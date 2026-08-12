from decimal import Decimal

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, inline_serializer

from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey

from .serializers import FeeQuoteInputSerializer
from .services import resolve_transaction_fee


class MerchantFeeQuoteView(APIView):
    authentication_classes = [MerchantApiKeyAuthentication]
    permission_classes = [HasMerchantApiKey]

    @extend_schema(
        summary="Preview the merchant fee for a payment",
        parameters=[FeeQuoteInputSerializer],
        responses=inline_serializer(
            name="MerchantFeeQuote",
            fields={
                "amount": serializers.DecimalField(max_digits=20, decimal_places=2),
                "currency": serializers.CharField(),
                "fee_rate": serializers.DecimalField(max_digits=7, decimal_places=2),
                "fee_amount": serializers.DecimalField(max_digits=20, decimal_places=2),
                "net_amount": serializers.DecimalField(max_digits=20, decimal_places=2),
                "fee_source": serializers.CharField(),
                "pricing_plan": serializers.CharField(required=False),
            },
        ),
    )
    def get(self, request):
        serializer = FeeQuoteInputSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        decision = resolve_transaction_fee(
            request.merchant,
            serializer.validated_data["amount"],
            serializer.validated_data["currency"],
        )
        payload = {
            "amount": str(decision.gross_amount),
            "currency": serializer.validated_data["currency"].upper(),
            "fee_rate": str(decision.fee_percentage.quantize(Decimal("0.01"))),
            "fee_amount": str(decision.fee_amount),
            "net_amount": str(decision.net_amount),
            "fee_source": decision.fee_source,
        }
        if decision.pricing_plan:
            payload["pricing_plan"] = decision.pricing_plan.code
        return Response(payload)
