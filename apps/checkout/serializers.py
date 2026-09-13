from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.billing.services import resolve_transaction_fee
from apps.checkout.services import create_checkout_session, create_qr_checkout_session
from apps.gateway.collection import PaymentGatewayError
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


class BasePaymentSessionSerializer(serializers.ModelSerializer):
    """Shared shape and behavior for both checkout flows.

    ``PaymentSessionSerializer`` (push to a typed alias) and
    ``QRPaymentSessionSerializer`` (scan AmatoPay's shared QR) are separate,
    single-purpose serializers/endpoints — they differ in exactly one place,
    how a session is created and whether a payer alias is involved — but
    everything else (fee resolution, instant-settlement gating, response
    shape, checkout URL) must stay identical between them.
    """

    total_amount = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True
    )
    net_amount = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True
    )
    checkout_url = serializers.SerializerMethodField()
    payment_reference = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

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

    def _resolve_fee(self, request, validated_data):
        decision = resolve_transaction_fee(
            request.merchant,
            validated_data["amount"],
            validated_data.get("currency", "BIF"),
        )
        return dict(
            fee_percentage=decision.fee_percentage,
            fee_amount=decision.fee_amount,
            fee_source=decision.fee_source,
            pricing_plan=decision.pricing_plan,
            plan_assignment=decision.plan_assignment,
            fee_calculated_at=decision.calculated_at,
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        view = self.context.get("view")
        if not view or getattr(view, "action", None) != "create":
            data.pop("client_secret", None)
        return data


_COMMON_FIELDS = [
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
    "payment_method",
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
_COMMON_READ_ONLY_FIELDS = [
    "session_id",
    "client_secret",
    "payment_method",
    "fee_percentage",
    "fee_amount",
    "fee_source",
    "status",
    "created_at",
    "payer_display_name",
    "expires_at",
]


class PaymentSessionSerializer(BasePaymentSessionSerializer):
    """Push a payment request to a payer's typed MOBILE alias."""

    payer_alias = serializers.CharField(max_length=160, trim_whitespace=True)

    class Meta:
        model = PaymentSession
        fields = [*_COMMON_FIELDS, "payer_alias"]
        read_only_fields = _COMMON_READ_ONLY_FIELDS

    def create(self, validated_data):
        request = self.context["request"]
        payer_alias = validated_data.pop("payer_alias")
        validated_data.update(self._resolve_fee(request, validated_data))
        try:
            return create_checkout_session(
                merchant=request.merchant,
                payer_alias=payer_alias,
                session_data=validated_data,
            )
        except AliasNotPayableError as exc:
            raise serializers.ValidationError({"payer_alias": str(exc)}) from exc
        except PaymentGatewayError as exc:
            # Already a curated, safe-to-show message — never the gateway's
            # own raw error body. Caught here so it becomes a clean 400
            # response instead of an opaque 500.
            raise serializers.ValidationError(str(exc)) from exc


class QRPaymentSessionSerializer(BasePaymentSessionSerializer):
    """Scan AmatoPay's shared QR to pay — the payer alias is required and
    verified upfront, exactly like the push flow. The difference from the
    push flow is the collection mechanism, not payer identity: AmatoPay
    never pushes a request to this alias, it only verifies who is expected
    to pay before the payer scans the code and pays through their own
    banking app.

    Only merchants with ``qr_payments_enabled`` may use this. Payment lands
    in AmatoPay's own fiduciary collection account exactly like the alias
    flow.
    """

    payer_alias = serializers.CharField(max_length=160, trim_whitespace=True)

    class Meta:
        model = PaymentSession
        fields = [*_COMMON_FIELDS, "payer_alias"]
        read_only_fields = _COMMON_READ_ONLY_FIELDS

    def validate(self, attrs):
        request = self.context.get("request")
        merchant = getattr(request, "merchant", None)
        if not (merchant and merchant.qr_payments_enabled):
            raise serializers.ValidationError(
                "This merchant is not enabled for QR payments. Contact "
                "AmatoPay to request the capability."
            )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        payer_alias = validated_data.pop("payer_alias")
        validated_data.update(self._resolve_fee(request, validated_data))
        try:
            return create_qr_checkout_session(
                merchant=request.merchant,
                session_data=validated_data,
                payer_alias=payer_alias,
            )
        except AliasNotPayableError as exc:
            raise serializers.ValidationError({"payer_alias": str(exc)}) from exc
        except PaymentGatewayError as exc:
            # Already a curated, safe-to-show message (e.g. QR locked,
            # misconfigured, expired) — never the gateway's own raw error
            # body. Caught here so it becomes a clean 400 response instead
            # of an opaque 500.
            raise serializers.ValidationError(str(exc)) from exc
