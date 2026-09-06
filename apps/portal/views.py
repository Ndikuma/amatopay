from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.views.generic import ListView
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.deliveries.services import (
    confirm_delivery_with_code,
    open_customer_delivery_claim,
)
from apps.payments.models import Payment
from apps.settlements.models import Settlement
from apps.webhooks.models import WebhookEvent
from apps.refunds.models import Refund
from apps.fiduciary.models import FundHold
from apps.merchants.models import (
    Merchant,
    MerchantActivity,
    MerchantApiKey,
    MerchantApplication,
    MerchantDocument,
    MerchantKYB,
    MerchantSettlementAccount,
    MerchantWebhookEndpoint,
)
from apps.merchants.services import activation_status as merchant_activation_status
from apps.billing.models import PlanRequest, PricingPlan
from apps.billing.services import (
    active_plan_assignment,
    initiate_plan_request_payment,
    resolve_transaction_fee,
)
from apps.webhooks.models import WebhookDelivery
from apps.webhooks.events import WEBHOOK_EVENT_TYPES as WEBHOOK_EVENTS
from apps.webhooks.security import validate_webhook_url
from apps.webhooks.services import emit_event
import secrets

from .forms import (
    DeliveryCodeConfirmationForm,
    MerchantApplicationForm,
    MerchantMissingProfileForm,
    PlanRequestForm,
)


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
    from apps.gateway.collection import PaymentGatewayError

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
            reverse("delivery_decision", args=[payment.reference])
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
        "deliveries": (
            WebhookDelivery.objects.filter(event__merchant=merchant)
            .select_related("event", "endpoint")
            .order_by("-created_at")[:25]
        ),
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
    accounts = merchant.settlement_accounts.order_by(
        "-is_primary", "-is_active", "-created_at"
    )
    status = merchant_activation_status(merchant)
    checklist = {
        "business": status["checks"]["business_identity"],
        "contact": status["checks"]["contact_details"],
        "source_of_funds": status["checks"]["source_of_funds"],
        "documents_submitted": status["checks"]["kyb_documents_submitted"],
        "documents_verified": status["checks"]["kyb_documents_verified"],
        "kyb": status["checks"]["kyb_approved"],
        "settlement": status["checks"]["settlement_account_verified"],
    }
    return render(
        request,
        "portal/profile.html",
        {
            "merchant": merchant,
            "kyb": kyb,
            "documents": documents,
            "settlement_accounts": accounts,
            "checklist": checklist,
            "readiness": status["readiness"],
            "activation_ready": status["can_operate"],
            "missing_profile_form": missing_profile_form,
        },
    )


# ---------------------------------------------------------------------------
# Public (unauthenticated) marketing + hosted-checkout pages
# ---------------------------------------------------------------------------


def pay(request, session_id):
    from apps.checkout.models import PaymentSession

    session = get_object_or_404(
        PaymentSession.objects.select_related("merchant"), session_id=session_id
    )
    return render(
        request,
        "checkout/pay.html",
        {"session": session, "merchant": session.merchant},
    )


def home(request):
    return render(request, "portal/home.html")


def docs(request):
    return render(request, "portal/docs.html")


class PlanListView(ListView):
    model = PricingPlan
    template_name = "billing/plan_list.html"
    context_object_name = "plans"

    def get_queryset(self):
        return PricingPlan.objects.filter(active=True).order_by("monthly_price")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["compare_features"] = [
            "Hosted checkout",
            "Signed webhooks",
            "Payment links",
            "API access",
            "Priority support",
            "KYB fast-track",
            "Dedicated account manager",
            "Custom settlement schedule",
            "SLA guarantee",
            "Compliance reporting",
        ]
        user = self.request.user
        ctx["user_authenticated"] = user.is_authenticated
        ctx["user_has_merchant"] = (
            user.is_authenticated
            and hasattr(user, "merchant_account")
            and user.merchant_account is not None
        )
        return ctx


@login_required
def request_plan_view(request, plan_id):
    plan = get_object_or_404(PricingPlan, id=plan_id)
    merchant = request.user.merchant_account

    if not merchant:
        messages.error(request, "You must have a merchant account to request a plan.")
        return redirect("plan_list")

    if request.method == "POST":
        form = PlanRequestForm(request.POST)
        if form.is_valid():
            plan_request = PlanRequest.objects.create(
                merchant=merchant,
                plan=plan,
                amount=plan.monthly_price,
                currency=plan.currency,
                payer_alias=form.cleaned_data["payer_alias"],
                note=form.cleaned_data["note"],
                initiated_by=request.user,
            )
            try:
                initiate_plan_request_payment(plan_request)
                return redirect("plan_list")
            except Exception as exc:
                messages.error(request, f"Could not initiate payment. Error: {exc}")
    else:
        form = PlanRequestForm()

    return render(request, "billing/request_plan.html", {"plan": plan, "form": form})


def _source_ip(request):
    # X-Real-IP is set by AmatoPay's trusted reverse proxy; never trust the first XFF hop.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


APPLICATION_DOCUMENTS = (
    # (application field, MerchantDocument.Type)
    ("registration_document", MerchantDocument.Type.REGISTRATION),
    ("tax_document", MerchantDocument.Type.TAX),
    ("license_document", MerchantDocument.Type.LICENSE),
    ("address_document", MerchantDocument.Type.ADDRESS),
    ("id_document", MerchantDocument.Type.ID),
    ("bank_document", MerchantDocument.Type.BANK),
)


@require_http_methods(["GET", "POST"])
def merchant_apply(request):
    form = MerchantApplicationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            email = form.cleaned_data["email"]
            contact_parts = form.cleaned_data["contact_name"].split(" ", 1)
            user = get_user_model().objects.create_user(
                username=email,
                email=email,
                password=form.cleaned_data["password"],
                first_name=contact_parts[0],
                last_name=contact_parts[1] if len(contact_parts) > 1 else "",
            )
            application = form.save(commit=False)
            application.applicant = user
            application.settlement_alias_type = (
                MerchantApplication.SettlementAliasType.MOBILE
            )
            application.source_ip = _source_ip(request)
            application.user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
            application.consented_at = timezone.now()
            application.save()

            merchant = Merchant.objects.create(
                owner=user,
                merchant_code=f"AMP-{application.id.hex[:12].upper()}",
                legal_name=application.legal_name,
                display_name=application.trading_name or application.legal_name,
                legal_form=application.legal_form,
                registration_number=application.registration_number,
                tax_id=application.tax_id,
                email=application.email,
                phone=application.phone,
                country=application.country,
                city=application.city,
                address=application.address,
                website=application.website,
                mcc=application.mcc,
                statement_descriptor=application.statement_descriptor,
                status=Merchant.Status.PENDING_KYB,
                metadata={"application_reference": application.reference},
            )
            MerchantKYB.objects.create(
                merchant=merchant,
                source_of_funds=application.source_of_funds,
                expected_monthly_volume=application.expected_monthly_volume,
                expected_monthly_transactions=application.expected_monthly_transactions,
            )
            MerchantSettlementAccount.objects.create(
                merchant=merchant,
                alias_type=application.settlement_alias_type,
                alias_value=application.settlement_alias,
                account_name=application.settlement_account_name,
                currency=merchant.default_currency,
                is_primary=True,
            )
            for field_name, doc_type in APPLICATION_DOCUMENTS:
                uploaded = getattr(application, field_name, None)
                if uploaded:
                    MerchantDocument.objects.create(
                        merchant=merchant,
                        document_type=doc_type,
                        file=uploaded,
                        verified=False,
                    )
        request.session["merchant_application_reference"] = application.reference
        return redirect("merchant_application_received")
    return render(request, "merchants/apply.html", {"form": form})


def merchant_application_received(request):
    reference = request.session.pop("merchant_application_reference", None)
    if not reference:
        return redirect("merchant_application")
    return render(
        request, "merchants/application_received.html", {"reference": reference}
    )


# ---------------------------------------------------------------------------
# Public customer delivery-decision portal  (/deliveries/)
# ---------------------------------------------------------------------------

DELIVERY_REPORT_REASONS = [
    ("not_received", "I never received the order or service"),
    ("incomplete", "The order or service was incomplete"),
    ("damaged", "What I received was damaged or not as described"),
    ("other", "Something else"),
]


def _eligible_delivery_payment(reference):
    return (
        Payment.objects.filter(
            reference=(reference or "").strip().upper(),
            status=Payment.Status.DELIVERY_PENDING,
        )
        .select_related("merchant", "fund_hold", "session")
        .first()
    )


def _delivery_unavailable_reason(payment):
    labels = {
        Payment.Status.CANCELLED: "This payment is cancelled.",
        Payment.Status.EXPIRED: "This payment has expired.",
        Payment.Status.FAILED: "This payment did not complete.",
        Payment.Status.REJECTED: "This payment was rejected.",
        Payment.Status.REFUNDED: "This payment was refunded.",
        Payment.Status.DISPUTED: "An investigation is already open for this payment.",
        Payment.Status.RELEASE_PENDING: "Delivery is already confirmed for this payment.",
        Payment.Status.SETTLEMENT_PROCESSING: "This payment is already being settled.",
        Payment.Status.SETTLED: "This payment is already settled.",
    }
    return labels.get(
        payment.status,
        "This payment is not currently waiting for a delivery decision.",
    )


def delivery_lookup(request):
    error = None
    if request.method == "POST":
        payment = _eligible_delivery_payment(request.POST.get("payment_reference"))
        if payment:
            return redirect("delivery_decision", reference=payment.reference)
        error = (
            "We could not find an eligible protected payment for that reference. "
            "Check the reference on your AmatoPay SMS and try again."
        )
    return render(request, "deliveries/lookup.html", {"error": error})


def delivery_decision(request, reference):
    payment = get_object_or_404(
        Payment.objects.select_related("merchant", "fund_hold", "session"),
        reference=(reference or "").strip().upper(),
    )

    if payment.status != Payment.Status.DELIVERY_PENDING:
        return render(
            request,
            "deliveries/unavailable.html",
            {"payment": payment, "reason": _delivery_unavailable_reason(payment)},
        )

    hold = getattr(payment, "fund_hold", None)
    merchant_ready = payment.merchant.settlement_accounts.filter(
        alias_type="MOBILE",
        verification_status="verified",
        is_primary=True,
        is_active=True,
        currency=payment.currency,
    ).exists()
    context = {
        "payment": payment,
        "merchant": payment.merchant,
        "deadline": getattr(hold, "release_eligible_at", None),
        "reasons": DELIVERY_REPORT_REASONS,
        "merchant_ready": merchant_ready,
        "code_locked": bool(payment.release_code_locked_at),
    }

    if request.method == "POST":
        decision = request.POST.get("decision")
        secure_code = (request.POST.get("secure_code") or "").strip()
        try:
            if decision == "confirm":
                confirm_delivery_with_code(payment, secure_code)
                return render(
                    request, "deliveries/confirmed.html", {"payment": payment}
                )
            if decision == "report":
                open_customer_delivery_claim(
                    payment,
                    secure_code,
                    reason=request.POST.get("reason") or "other",
                    description=(request.POST.get("description") or "").strip(),
                )
                return render(
                    request, "deliveries/reported.html", {"payment": payment}
                )
            context["error"] = "Choose whether you received the order."
        except APIException as exc:
            payment.refresh_from_db()
            detail = getattr(exc, "detail", None)
            context["error"] = str(detail if detail else exc)
        context["submitted_decision"] = decision
        context["description"] = request.POST.get("description", "")
        context["selected_reason"] = request.POST.get("reason", "")

    return render(request, "deliveries/decision.html", context)
