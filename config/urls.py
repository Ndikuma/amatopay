from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views

from apps.merchants.views import MerchantPingView
from apps.portal.views import (
    PlanListView,
    delivery_decision,
    delivery_lookup,
    docs,
    home,
    merchant_application_received,
    merchant_apply,
    pay,
    request_plan_view,
)
from config.health import live, ready
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
API_PREFIX = "api/v1/"

urlpatterns = [
    path("health/live/", live, name="health_live"),
    path("health/ready/", ready, name="health_ready"),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/portal/favicon.svg", permanent=True),
    ),
    path("", home, name="home"),
    path("merchants/apply/", merchant_apply, name="merchant_application"),
    path(
        "merchants/apply/received/",
        merchant_application_received,
        name="merchant_application_received",
    ),
    path("developers/", docs, name="developer_docs"),
    path("deliveries/", delivery_lookup, name="delivery_lookup"),
    path("deliveries/<str:reference>/", delivery_decision, name="delivery_decision"),
    path("billing/plans/", PlanListView.as_view(), name="plan_list"),
    path(
        "billing/plans/request/<uuid:plan_id>/",
        request_plan_view,
        name="request_plan",
    ),
    path(
        "account/sign-in/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("account/sign-out/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "account/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            success_url="/account/password-reset/sent/",
        ),
        name="password_reset",
    ),
    path(
        "account/password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "account/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url="/account/reset/complete/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "account/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("admin/", admin.site.urls),
    path("security/", include("apps.security.urls")),
    path("dashboard/", include("apps.portal.urls")),
    path("pay/<uuid:session_id>/", pay, name="hosted_checkout"),
    path(f"{API_PREFIX}ping/", MerchantPingView.as_view(), name="merchant_ping"),
    path(f"{API_PREFIX}checkout/", include("apps.checkout.urls")),
    path(f"{API_PREFIX}payments/", include("apps.payments.urls")),
    path(f"{API_PREFIX}fees/", include("apps.billing.urls")),
]

urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="api_schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="api_schema"),
            name="swagger_ui",
        ),
        path(
            "api/redoc/",
            SpectacularRedocView.as_view(url_name="api_schema"),
            name="redoc",
        ),]

if settings.DEBUG:
    # This allows Django's development server to serve static files.
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
