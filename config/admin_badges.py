from apps.compliance.models import SuspiciousTransaction
from apps.deliveries.models import ProtectionClaim
from apps.fiduciary.models import FundHold
from apps.gateway.models import GatewayConfig, GatewayRequest
from apps.merchants.models import MerchantApplication, MerchantKYB
from apps.payments.models import Payment
from apps.refunds.models import Refund
from apps.settlements.models import Settlement
from apps.webhooks.models import WebhookDelivery


def _badge(count):
    return str(count) if count else None


def pending_payments(request):
    return _badge(
        Payment.objects.filter(
            status__in=["collection_pending", "awaiting_approval", "processing"]
        ).count()
    )


def protected_funds(request):
    return _badge(
        FundHold.objects.exclude(status__in=["released", "refunded"]).count()
    )


def pending_settlements(request):
    return _badge(Settlement.objects.filter(status__in=["pending", "processing"]).count())


def pending_refunds(request):
    return _badge(Refund.objects.filter(status__in=["requested", "processing"]).count())


def open_claims(request):
    return _badge(
        ProtectionClaim.objects.exclude(
            status__in=["won_customer", "won_merchant", "closed"]
        ).count()
    )


def kyb_reviews(request):
    return _badge(MerchantKYB.objects.filter(decision__in=["pending", "more_info"]).count())


def merchant_applications(request):
    return _badge(
        MerchantApplication.objects.filter(
            status__in=["submitted", "under_review", "more_info"]
        ).count()
    )


def gateway_state(request):
    return "Live" if GatewayConfig.active() else "Setup"


_IN_FLIGHT = ["pending", "awaiting_approval", "processing"]


def pending_collections(request):
    return _badge(
        GatewayRequest.objects.filter(
            rail=GatewayRequest.Rail.COLLECTION, status__in=_IN_FLIGHT
        ).count()
    )


def pending_p2p(request):
    return _badge(
        GatewayRequest.objects.filter(
            rail=GatewayRequest.Rail.P2P, status__in=_IN_FLIGHT
        ).count()
    )


def compliance_attention(request):
    return _badge(SuspiciousTransaction.objects.filter(status="open").count())


def webhook_failures(request):
    return _badge(WebhookDelivery.objects.filter(status="failed").count())


def security_alerts(request):
    try:
        from apps.security.models import SecurityAlert

        return _badge(SecurityAlert.objects.filter(resolved=False).count())
    except Exception:
        return None
