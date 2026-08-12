from django.urls import path

from .public_views import PlanListView

app_name = "billing_public"

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="plan_list"),
]
