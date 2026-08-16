from django.urls import path

from .public_views import PlanListView, request_plan_view

app_name = "billing_public"

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="plan_list"),
    path('plans/request/<uuid:plan_id>/', request_plan_view, name='request_plan'),
]
