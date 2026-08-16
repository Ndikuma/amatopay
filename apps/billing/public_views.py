from django.views.generic import ListView
from django.shortcuts import render, get_object_or_404
from apps.merchants.models import Merchant


from .models import PricingPlan


class PlanListView(ListView):
    model = PricingPlan
    template_name = "billing/plan_list.html"
    context_object_name = "plans"

    def get_queryset(self):
        return PricingPlan.objects.filter(active=True).order_by("monthly_price")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["compare_features"] = [
            "Hosted checkout", "Signed webhooks", "Payment links", "API access",

            "Priority support", "KYB fast-track", "Dedicated account manager",
            "Custom settlement schedule", "SLA guarantee", "Compliance reporting",
        ]
        user = self.request.user
        ctx["user_authenticated"] = user.is_authenticated
        ctx["user_has_merchant"] = (
            user.is_authenticated
            and hasattr(user, "merchant_account")
            and user.merchant_account is not None
        )
        return ctx

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .forms import PlanRequestForm
from .models import PricingPlan, PlanRequest
from .services import initiate_plan_request_payment

@login_required
def request_plan_view(request, plan_id):
    plan = get_object_or_404(PricingPlan, id=plan_id)
    merchant = request.user.merchant_account

    if not merchant:
        messages.error(request, "You must have a merchant account to request a plan.")
        return redirect("billing_public:plan_list")

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
                return redirect("billing_public:request_submitted", plan_request_id=plan_request.id)
            except Exception as e:
                messages.error(request, f"Could not initiate payment. Error: {e}")
    else:
        form = PlanRequestForm()

    return render(request, "billing/request_plan.html", {
        "plan": plan,
        "form": form,
    })
