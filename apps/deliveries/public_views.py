from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import APIException

from apps.payments.models import Payment

from .forms import PublicDeliveryDecisionForm
from .services import (
    confirm_delivery_with_code,
    open_customer_delivery_claim,
    request_delivery_review,
)


def _delivery_decision_is_available(payment):
    return bool(
        payment.release_code_confirmed_at
        or payment.status
        in {Payment.Status.DELIVERY_PENDING, Payment.Status.DISPUTED}
    )


@require_http_methods(["GET", "POST"])
def delivery_lookup(request):
    reference = request.POST.get("payment_reference", "").strip().upper()
    error = ""
    if request.method == "POST":
        if not reference.startswith("AMP-PAY-") or len(reference) > 64:
            error = "Enter a valid AmatoPay payment reference."
        elif Payment.objects.filter(
            reference=reference,
            status__in=[Payment.Status.DELIVERY_PENDING, Payment.Status.DISPUTED],
        ).exists() or Payment.objects.filter(
            reference=reference, release_code_confirmed_at__isnull=False
        ).exists():
            return redirect("customer_delivery", reference=reference)
        else:
            error = "We could not find an eligible protected payment."
    return render(
        request,
        "deliveries/delivery_lookup.html",
        {"payment_reference": reference, "error": error},
    )


@require_http_methods(["GET", "POST"])
def customer_delivery(request, reference):
    payment = get_object_or_404(
        Payment.objects.select_related("merchant", "session"), reference=reference
    )
    form = PublicDeliveryDecisionForm(request.POST or None, request.FILES or None)
    completed = payment.release_code_confirmed_at is not None
    active_claim = payment.protection_claims.exclude(status="closed").first()
    try:
        hold = payment.fund_hold
    except ObjectDoesNotExist:
        hold = None

    if request.method == "POST" and form.is_valid() and not completed and not active_claim:
        try:
            if form.cleaned_data["decision"] == form.Decision.CONFIRM:
                confirm_delivery_with_code(payment, form.cleaned_data["secure_code"])
                messages.success(request, "Delivery confirmed. Thank you.")
            elif form.cleaned_data["decision"] == form.Decision.REVIEW:
                proof_method = form.cleaned_data["proof_method"]
                request_delivery_review(
                    payment,
                    form.cleaned_data["secure_code"],
                    payer_alias=form.cleaned_data["payer_alias"],
                    reason=f"alternative_proof:{proof_method}",
                    description=form.cleaned_data["description"].strip(),
                    evidence_file=form.cleaned_data["evidence_file"],
                )
                messages.success(
                    request,
                    "Manual delivery review opened. Funds stay protected while AmatoPay verifies the proof.",
                )
            else:
                open_customer_delivery_claim(
                    payment,
                    form.cleaned_data["secure_code"],
                    payer_alias=form.cleaned_data["payer_alias"],
                    reason=form.cleaned_data["reason"],
                    description=form.cleaned_data["description"].strip(),
                    evidence_file=form.cleaned_data["evidence_file"],
                )
                messages.success(
                    request,
                    "Your delivery problem was received. Funds stay protected while AmatoPay investigates.",
                )
            return redirect("customer_delivery", reference=payment.reference)
        except APIException as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                detail = detail.get("detail", "Unable to process this request.")
            form.add_error(None, str(detail))

    available = _delivery_decision_is_available(payment)

    return render(
        request,
        "deliveries/customer_delivery.html",
        {
            "payment": payment,
            "form": form,
            "completed": completed,
            "active_claim": active_claim,
            "protection_deadline": hold.release_eligible_at if hold else None,
            "available": available,
        },
    )
