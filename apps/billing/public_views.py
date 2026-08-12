from django.views.generic import ListView

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
            "Delivery protection", "Request logs", "Refunds", "Team workspaces",
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
