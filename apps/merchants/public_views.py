from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import MerchantApplicationForm
from .models import Merchant, MerchantApplication, MerchantKYB, MerchantSettlementAccount


def _source_ip(request):
    # X-Real-IP is set by AmatoPay's trusted reverse proxy; never trust the first XFF hop.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


@require_http_methods(["GET", "POST"])
def apply(request):
    form = MerchantApplicationForm(request.POST or None)
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
            application.settlement_alias_type = MerchantApplication.SettlementAliasType.MOBILE
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
                status=Merchant.Status.PENDING_KYB,
                metadata={"application_reference": application.reference},
            )
            MerchantKYB.objects.create(
                merchant=merchant,
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
        request.session["merchant_application_reference"] = application.reference
        return redirect("merchant_application_received")
    return render(request, "merchants/apply.html", {"form": form})


def received(request):
    reference = request.session.pop("merchant_application_reference", None)
    if not reference:
        return redirect("merchant_application")
    return render(request, "merchants/application_received.html", {"reference": reference})
