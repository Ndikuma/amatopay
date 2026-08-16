from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.deliveries.services import confirm_delivery_with_code
from apps.payments.models import Payment
from apps.settlements.models import Settlement
from apps.webhooks.models import WebhookEvent
from apps.refunds.models import Refund
from apps.fiduciary.models import FundHold
from apps.merchants.models import Merchant, MerchantActivity, MerchantApiKey
from apps.merchants.models import MerchantWebhookEndpoint
from apps.billing.services import (
    active_plan_assignment,
    initiate_plan_request_payment,
    resolve_transaction_fee,
)
from apps.webhooks.models import WebhookDelivery
from apps.webhooks.security import validate_webhook_url
from apps.webhooks.services import emit_event
import secrets

from .forms import DeliveryCodeConfirmationForm, MerchantMissingProfileForm


def _merchant(request):
    try:
        return request.user.merchant_account
    except ObjectDoesNotExist:
        return None





def _no_merchant(request):
    return render(request, "portal/no_merchant.html")


def _payment_timeline(payment):
    labels = dict(Payment.Status.choices)
    return [
        {
            "status": event.status,
            "label": labels.get(event.status, event.status.replace("_", " ").title()),
            "created_at": event.created_at,
            "reason": event.reason,
        }
        for event in payment.history.order_by("created_at")
    ]


@login_required
def dashboard(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)

    payments = Payment.objects.filter(merchant=merchant)
    successful_payments = payments.filter(
        status__in=[
            "paid",
            "funds_held",
            "delivery_pending",
            "release_pending",
            "settlement_processing",
            "settled",
        ]
    )
    stats = {
        "volume": successful_payments.aggregate(value=Sum("amount"))["value"] or 0,
        "payments": payments.count(),
        "successful": successful_payments.count(),
        "settlements": Settlement.objects.filter(
            merchant=merchant,
            status="completed",
        ).aggregate(value=Sum("net_amount"))["value"]
        or 0,
    }
    return render(
        request,
        "portal/dashboard.html",
        {
            "merchant": merchant,
            "stats": stats,
            "recent_payments": payments.select_related("session").order_by(
                "-created_at"
            )[:10],
        },
    )


@login_required
def billing(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)

    now = timezone.now()
    assignment = active_plan_assignment(
        merchant, merchant.default_currency, at=now
    )
    if assignment:
        month_start = timezone.localtime(now).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        successful_statuses = [
            Payment.Status.PAID,
            Payment.Status.FUNDS_HELD,
            Payment.Status.DELIVERY_PENDING,
            Payment.Status.RELEASE_PENDING,
            Payment.Status.SETTLEMENT_PROCESSING,
            Payment.Status.SETTLED,
        ]
        used = Payment.objects.filter(
            merchant=merchant,
            plan_assignment=assignment,
            created_at__gte=month_start,
            status__in=successful_statuses,
        ).count()
        limit = assignment.monthly_transaction_limit
        remaining = max(limit - used, 0) if limit is not None else None
        usage_percent = min(round(used / limit * 100), 100) if limit else 0
        plan = assignment.plan
        pricing = {
            "mode": "plan",
            "assignment": assignment,
            "name": plan.name,
            "description": plan.description,
            "price": assignment.effective_monthly_price,
            "currency": plan.currency,
            "limit": limit,
            "base_limit": limit,
            "used": used,
            "remaining": remaining,
            "usage_percent": usage_percent,
        }
    else:
        try:
            decision = resolve_transaction_fee(
                merchant, 100, merchant.default_currency, at=now
            )
            pricing = {
                "mode": "payg",
                "rate": decision.fee_percentage,
                "plan": decision.pricing_plan,
                "currency": merchant.default_currency,
            }
        except Exception:
            pricing = {
                "mode": "payg",
                "rate": None,
                "plan": None,
                "currency": merchant.default_currency,
            }
    return render(
        request,
        "portal/billing.html",
        {"merchant": merchant, "pricing": pricing},
    )




@login_required
def plan_select(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    now = timezone.now()
    assignment = active_plan_assignment(merchant, merchant.default_currency, at=now)
    if assignment:
        month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = Payment.objects.filter(
            merchant=merchant,
            plan_assignment=assignment,
            created_at__gte=month_start,
            status__in=[
                Payment.Status.PAID, Payment.Status.FUNDS_HELD,
                Payment.Status.DELIVERY_PENDING, Payment.Status.RELEASE_PENDING,
                Payment.Status.SETTLEMENT_PROCESSING, Payment.Status.SETTLED,
            ],
        ).count()
        pricing = {
            "mode": "plan",
            "name": assignment.plan.name,
            "plan_code": assignment.plan.code,
            "used": used,
            "limit": assignment.monthly_transaction_limit,
        }
    else:
        pricing = {"mode": "payg", "plan_code": None}

    from apps.billing.models import PricingPlan
    plans = PricingPlan.objects.filter(active=True).order_by("monthly_price")
    return render(request, "portal/plan_select.html", {
        "merchant": merchant,
        "pricing": pricing,
        "plans": plans,
    })


@login_required
@require_POST
def billing_request_plan(request):
    from apps.billing.models import PricingPlan, PlanRequest
    from apps.gateway.rtp import PaymentGatewayError

    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)

    plan_code = request.POST.get("plan_code", "").strip()
    note = request.POST.get("note", "").strip()[:500]
    payer_alias = request.POST.get("payer_alias", "").strip()

    plan = PricingPlan.objects.filter(code=plan_code, active=True).first()
    if not plan:
        messages.error(request, "Invalid plan selected.")
        return redirect("portal:plan-select")

    if not payer_alias:
        messages.error(request, "A payer alias (mobile number) is required to initiate payment.")
        return redirect("portal:plan-select")

    amount = plan.monthly_price
    if not amount:
        messages.error(request, "This plan requires a custom quote. Contact support.")
        return redirect("portal:plan-select")

    plan_request = PlanRequest.objects.create(
        merchant=merchant,
        plan=plan,
        amount=amount,
        currency=plan.currency,
        payer_alias=payer_alias,
        note=note,
        initiated_by=request.user,
    )

    try:
        initiate_plan_request_payment(plan_request)
        messages.success(
            request,
            f"Payment for the {plan.name} plan has been initiated. "
            "Approve the request on your mobile to activate your plan.",
        )
    except PaymentGatewayError as exc:
        plan_request.status = PlanRequest.Status.CANCELLED
        plan_request.save(update_fields=["status", "updated_at"])
        messages.error(request, str(exc))
    except Exception:
        plan_request.status = PlanRequest.Status.CANCELLED
        plan_request.save(update_fields=["status", "updated_at"])
        messages.error(request, "Plan payment could not be initiated. Please try again.")
    return redirect("portal:billing")


@login_required
def payments(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)

    merchant_payments = (
        Payment.objects.filter(merchant=merchant)
        .select_related("session")
        .order_by("-created_at")[:200]
    )
    return render(
        request,
        "portal/payments.html",
        {"merchant": merchant, "payments": merchant_payments},
    )


@login_required
def payment_detail(request, reference):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    payment = get_object_or_404(
        Payment.objects.filter(merchant=merchant)
        .select_related("session")
        .prefetch_related("history"),
        reference=reference,
    )
    history = _payment_timeline(payment)
    settlement_account = merchant.settlement_accounts.filter(
        alias_type="MOBILE",
        verification_status="verified",
        is_primary=True,
        is_active=True,
        currency=payment.currency,
    ).first()
    can_confirm = (
        payment.status == Payment.Status.DELIVERY_PENDING
        and not payment.release_code_confirmed_at
        and not payment.release_code_locked_at
        and settlement_account is not None
    )
    delivery_decision_url = None
    if payment.release_code_confirmed_at or payment.status in {
        Payment.Status.DELIVERY_PENDING,
        Payment.Status.DISPUTED,
    }:
        delivery_decision_url = request.build_absolute_uri(
            reverse("customer_delivery", args=[payment.reference])
        )
    form = DeliveryCodeConfirmationForm(
        expected_reference=payment.reference,
        initial={"payment_reference": payment.reference},
    )
    return render(
        request,
        "portal/payment_detail.html",
        {
            "merchant": merchant,
            "payment": payment,
            "history": history,
            "form": form,
            "can_confirm": can_confirm,
            "settlement_account": settlement_account,
            "delivery_decision_url": delivery_decision_url,
        },
    )


@login_required
@require_POST
def payment_confirm_delivery(request, reference):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    payment = get_object_or_404(Payment, merchant=merchant, reference=reference)
    form = DeliveryCodeConfirmationForm(
        request.POST, expected_reference=payment.reference
    )
    if form.is_valid():
        try:
            confirm_delivery_with_code(
                payment,
                form.cleaned_data["secure_code"],
                {"merchant_reference": payment.session.order_number},
            )
        except APIException as exc:
            form.add_error("secure_code", str(exc.detail))
        else:
            messages.success(
                request,
                "Delivery confirmed. The payment is now being released for settlement.",
            )
            return redirect("portal:payment-detail", reference=payment.reference)
    payment.refresh_from_db()
    history = _payment_timeline(payment)
    settlement_account = merchant.settlement_accounts.filter(
        alias_type="MOBILE",
        verification_status="verified",
        is_primary=True,
        is_active=True,
        currency=payment.currency,
    ).first()
    return render(
        request,
        "portal/payment_detail.html",
        {
            "merchant": merchant,
            "payment": payment,
            "history": history,
            "form": form,
            "can_confirm": True,
            "settlement_account": settlement_account,
        },
        status=400,
    )


@login_required
def settlements(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    items = (
        Settlement.objects.filter(merchant=merchant)
        .select_related("payment")
        .order_by("-created_at")[:200]
    )
    return render(
        request, "portal/settlements.html", {"merchant": merchant, "settlements": items}
    )


@login_required
def refunds(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    refund_queryset = (
        Refund.objects.filter(payment__merchant=merchant)
        .select_related("payment")
        .order_by("-created_at")
    )
    completed = refund_queryset.filter(status=Refund.Status.COMPLETED)
    pending = refund_queryset.filter(status__in=[Refund.Status.REQUESTED, Refund.Status.APPROVED, Refund.Status.PROCESSING])
    return render(
        request,
        "portal/refunds.html",
        {
            "merchant": merchant,
            "refunds": refund_queryset[:200],
            "completed_total": completed.aggregate(total=Sum("amount"))["total"] or 0,
            "completed_count": completed.count(),
            "pending_count": pending.count(),
        },
    )


@login_required
def trust(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)

    holds = (
        FundHold.objects.filter(payment__merchant=merchant)
        .select_related("payment", "payment__session")
        .order_by("-created_at")
    )
    active_hold_statuses = [
        "held",
        "delivery_pending",
        "delivery_confirmed",
        "disputed",
        "release_pending",
        "refund_pending",
        "frozen",
    ]
    active_holds = holds.filter(status__in=active_hold_statuses)
    try:
        kyb = merchant.kyb
    except ObjectDoesNotExist:
        kyb = None

    context = {
        "merchant": merchant,
        "kyb": kyb,
        "verified_documents": merchant.kyb_documents.filter(verified=True).count(),
        "document_count": merchant.kyb_documents.count(),
        "settlement_accounts": merchant.settlement_accounts.order_by(
            "-is_primary", "-created_at"
        ),
        "held_total": active_holds.aggregate(value=Sum("amount"))["value"] or 0,
        "active_hold_count": active_holds.count(),
        "holds": holds[:12],
    }
    return render(request, "portal/trust.html", context)


@login_required
def developers(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)

    context = {
        "merchant": merchant,
        "keys": merchant.api_keys.order_by("-created_at"),
        "webhooks": merchant.webhook_endpoints.order_by("-created_at"),
        "events": WebhookEvent.objects.filter(merchant=merchant).order_by(
            "-created_at"
        )[:20],
        "webhook_event_choices": sorted(WEBHOOK_EVENTS),
        "new_webhook_secret": request.session.pop("new_webhook_secret", None),
        "new_webhook_endpoint_id": request.session.pop("new_webhook_endpoint_id", None),
    }
    return render(request, "portal/developers.html", context)


def _record_key_activity(request, merchant, action, description, key):
    ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")
    MerchantActivity.objects.create(
        merchant=merchant,
        actor=request.user,
        action=action,
        description=description,
        ip_address=ip or None,
        metadata={"key_id": str(key.id), "prefix": key.prefix},
    )


def _record_webhook_activity(request, merchant, action, description, endpoint):
    MerchantActivity.objects.create(
        merchant=merchant,
        actor=request.user,
        action=action,
        description=description,
        ip_address=request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or None,
        metadata={"endpoint_id": str(endpoint.id), "url": endpoint.url},
    )


WEBHOOK_EVENTS = {
    "payment.paid",
    "payment.failed",
    "settlement.completed",
}


@login_required
@require_POST
def webhook_create(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    if merchant.webhook_endpoints.filter(active=True).count() >= 5:
        messages.error(request, "A merchant can configure up to five webhook endpoints.")
        return redirect("portal:developers")
    url = request.POST.get("url", "").strip()
    try:
        validate_webhook_url(url)
    except Exception as exc:
        messages.error(request, str(getattr(exc, "detail", exc)))
        return redirect("portal:developers")
    if merchant.webhook_endpoints.filter(url__iexact=url).exists():
        messages.error(request, "This webhook URL is already configured.")
        return redirect("portal:developers")
    selected = [event for event in request.POST.getlist("events") if event in WEBHOOK_EVENTS]
    endpoint = MerchantWebhookEndpoint.objects.create(
        merchant=merchant,
        url=url,
        description=request.POST.get("description", "").strip()[:160],
        events=selected or ["*"],
        secret="whsec_" + secrets.token_urlsafe(32),
        active=True,
    )
    _record_webhook_activity(request, merchant, "webhook.created", "Created webhook endpoint", endpoint)
    request.session["new_webhook_secret"] = endpoint.secret
    request.session["new_webhook_endpoint_id"] = str(endpoint.id)
    return redirect("portal:developers")


def _merchant_endpoint(request, endpoint_id):
    merchant = _merchant(request)
    if not merchant:
        raise PermissionDenied("No merchant workspace is available.")
    return merchant, get_object_or_404(merchant.webhook_endpoints, id=endpoint_id)


@login_required
@require_POST
def webhook_toggle(request, endpoint_id):
    merchant, endpoint = _merchant_endpoint(request, endpoint_id)
    endpoint.active = not endpoint.active
    endpoint.save(update_fields=["active", "updated_at"])
    _record_webhook_activity(request, merchant, "webhook.toggled", f"{'Activated' if endpoint.active else 'Paused'} webhook endpoint", endpoint)
    return redirect("portal:developers")


@login_required
@require_POST
def webhook_rotate_secret(request, endpoint_id):
    merchant, endpoint = _merchant_endpoint(request, endpoint_id)
    endpoint.secret = "whsec_" + secrets.token_urlsafe(32)
    endpoint.save(update_fields=["secret", "updated_at"])
    _record_webhook_activity(request, merchant, "webhook.secret_rotated", "Rotated webhook signing secret", endpoint)
    request.session["new_webhook_secret"] = endpoint.secret
    request.session["new_webhook_endpoint_id"] = str(endpoint.id)
    return redirect("portal:developers")


@login_required
@require_POST
def webhook_test(request, endpoint_id):
    merchant, endpoint = _merchant_endpoint(request, endpoint_id)
    event = emit_event(
        merchant,
        "endpoint.test",
        {"message": "AmatoPay webhook endpoint test", "endpoint_id": str(endpoint.id)},
        "webhook_endpoint",
        endpoint.id,
    )
    WebhookDelivery.objects.get_or_create(event=event, endpoint=endpoint)
    _record_webhook_activity(request, merchant, "webhook.test_queued", "Queued webhook endpoint test", endpoint)
    messages.success(request, "Test event queued. Delivery status will update shortly.")
    return redirect("portal:developers")




@login_required
@require_POST
def api_key_create(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    name = request.POST.get("name", "").strip()[:80] or "Integration key"
    if merchant.status != merchant.Status.ACTIVE:
        raise PermissionDenied("API keys require an active merchant account.")
    key, raw = MerchantApiKey.issue(merchant, name)
    _record_key_activity(
        request, merchant, "api_key.created", f"Created API key “{name}”", key
    )
    context = {
        "merchant": merchant,
        "keys": merchant.api_keys.order_by("-created_at"),
        "webhooks": merchant.webhook_endpoints.order_by("-created_at"),
        "events": WebhookEvent.objects.filter(merchant=merchant).order_by(
            "-created_at"
        )[:20],
        "new_api_key": raw,
        "new_api_key_name": name,
        "webhook_event_choices": sorted(WEBHOOK_EVENTS),
    }
    return render(request, "portal/developers.html", context)


@login_required
@require_POST
def api_key_rotate(request, key_id):
    merchant = _merchant(request)
    key = get_object_or_404(merchant.api_keys, id=key_id)
    raw = key.rotate()
    _record_key_activity(
        request, merchant, "api_key.rotated", f"Rotated API key “{key.name}”", key
    )
    context = {
        "merchant": merchant,
        "keys": merchant.api_keys.order_by("-created_at"),
        "webhooks": merchant.webhook_endpoints.order_by("-created_at"),
        "events": WebhookEvent.objects.filter(merchant=merchant).order_by(
            "-created_at"
        )[:20],
        "new_api_key": raw,
        "new_api_key_name": key.name,
        "webhook_event_choices": sorted(WEBHOOK_EVENTS),
    }
    return render(request, "portal/developers.html", context)


@login_required
@require_POST
def api_key_revoke(request, key_id):
    merchant = _merchant(request)
    key = get_object_or_404(merchant.api_keys, id=key_id)
    key.revoke()
    _record_key_activity(
        request, merchant, "api_key.revoked", f"Revoked API key “{key.name}”", key
    )
    return redirect("portal:developers")


@login_required
def profile(request):
    merchant = _merchant(request)
    if not merchant:
        return _no_merchant(request)
    if request.method == "POST":
        with transaction.atomic():
            merchant = Merchant.objects.select_for_update().get(pk=merchant.pk)
            missing_profile_form = MerchantMissingProfileForm(
                request.POST, instance=merchant
            )
            if missing_profile_form.is_valid():
                completed_fields = list(missing_profile_form.fields)
                if completed_fields:
                    missing_profile_form.save()
                    MerchantActivity.objects.create(
                        merchant=merchant,
                        actor=request.user,
                        action="profile.missing_information_completed",
                        description="Owner completed previously missing profile information.",
                        metadata={"fields": completed_fields},
                    )
                    messages.success(
                        request,
                        "Missing information saved. Contact Support if a correction is needed.",
                    )
                return redirect("portal:profile")
    else:
        missing_profile_form = MerchantMissingProfileForm(instance=merchant)
    try:
        kyb = merchant.kyb
    except ObjectDoesNotExist:
        kyb = None
    documents = merchant.kyb_documents.order_by("document_type", "-created_at")
    owners = merchant.beneficial_owners.order_by("-ownership_percent", "full_name")
    accounts = merchant.settlement_accounts.order_by(
        "-is_primary", "-is_active", "-created_at"
    )
    checklist = {
        "business": bool(
            merchant.registration_number and merchant.tax_id and merchant.legal_name
        ),
        "contact": bool(merchant.email and merchant.phone and merchant.address),
        "kyb": bool(kyb and kyb.verified and kyb.decision == "approved"),
        "documents": documents.filter(verified=True).exists(),
        "owners": owners.exists(),
        "settlement": accounts.filter(
            verification_status="verified", is_primary=True, is_active=True
        ).exists(),
    }
    readiness = round(sum(checklist.values()) / len(checklist) * 100)
    return render(
        request,
        "portal/profile.html",
        {
            "merchant": merchant,
            "kyb": kyb,
            "documents": documents,
            "owners": owners,
            "settlement_accounts": accounts,
            "checklist": checklist,
            "readiness": readiness,
            "missing_profile_form": missing_profile_form,
        },
    )
