from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.billing.services import resolve_transaction_fee
from apps.checkout.services import create_checkout_session
from apps.gateway.services import AliasNotPayableError

from .models import PaymentSession


class MerchantAliasVerificationSerializer(serializers.Serializer):
    payer_alias = serializers.CharField(max_length=160, trim_whitespace=True)


class MerchantAliasVerificationResultSerializer(serializers.Serializer):
    alias_type = serializers.CharField()
    payer_alias = serializers.CharField()
    found = serializers.BooleanField()
    status = serializers.CharField()
    customer_full_name = serializers.CharField()
    currency = serializers.CharField()


class PaymentSessionSerializer(serializers.ModelSerializer):
    payer_alias = serializers.CharField(max_length=160, trim_whitespace=True)
    total_amount = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True
    )
    net_amount = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True
    )
    checkout_url = serializers.SerializerMethodField()
    payment_reference = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = PaymentSession
        fields = [
            "session_id",
            "client_secret",
            "order_number",
            "description",
            "amount",
            "fee_percentage",
            "fee_amount",
            "net_amount",
            "fee_source",
            "total_amount",
            "currency",
            "payer_alias",
            "payer_display_name",
            "return_url",
            "require_delivery_confirmation",
            "expires_at",
            "status",
            "metadata",
            "checkout_url",
            "payment_reference",
            "payment_status",
            "created_at",
        ]
        read_only_fields = [
            "session_id",
            "client_secret",
            "fee_percentage",
            "fee_amount",
            "fee_source",
            "status",
            "created_at",
            "payer_display_name",
            "expires_at",
        ]

    def get_checkout_url(self, obj) -> str:
        request = self.context.get("request")
        path = f"/pay/{obj.session_id}/"
        return request.build_absolute_uri(path) if request else path

    def get_payment_reference(self, obj) -> str:
        try:
            payment = obj.payment
        except ObjectDoesNotExist:
            payment = None
        return payment.reference if payment else ""

    def get_payment_status(self, obj) -> str:
        try:
            payment = obj.payment
        except ObjectDoesNotExist:
            payment = None
        return payment.status if payment else obj.status

    def validate_require_delivery_confirmation(self, value):
        request = self.context.get("request")
        merchant = getattr(request, "merchant", None)
        if value is False and not (merchant and merchant.instant_settlement_enabled):
            raise serializers.ValidationError(
                "This merchant is not enabled for instant settlement. Contact "
                "AmatoPay to request the capability."
            )
        return value

    def create(self, validated_data):
        request = self.context["request"]
        decision = resolve_transaction_fee(
            request.merchant,
            validated_data["amount"],
            validated_data.get("currency", "BIF"),
        )
        payer_alias = validated_data.pop("payer_alias")
        validated_data.update(
            fee_percentage=decision.fee_percentage,
            fee_amount=decision.fee_amount,
            fee_source=decision.fee_source,
            pricing_plan=decision.pricing_plan,
            plan_assignment=decision.plan_assignment,
            fee_calculated_at=decision.calculated_at,
        )
        try:
            return create_checkout_session(
                merchant=request.merchant,
                payer_alias=payer_alias,
                session_data=validated_data,
            )
        except AliasNotPayableError as exc:
            raise serializers.ValidationError({"payer_alias": str(exc)}) from exc

    def to_representation(self, instance):
        data = super().to_representation(instance)
        view = self.context.get("view")
        if not view or getattr(view, "action", None) != "create":
            data.pop("client_secret", None)
        return data
