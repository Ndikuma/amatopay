from django.contrib import admin
from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views

from apps.portal.public_views import docs, home, pay
from apps.merchants.public_views import apply as merchant_apply, received as merchant_received
from apps.deliveries.public_views import customer_delivery, delivery_lookup
from config.health import live, ready

API_PREFIX = "api/v1/"

urlpatterns = [
    path("health/live/", live, name="health_live"),
    path("health/ready/", ready, name="health_ready"),
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/portal/favicon.svg", permanent=True),
    ),
    path("", home, name="home"),
    path("", include("apps.billing.public_urls")),
    path("merchants/apply/", merchant_apply, name="merchant_application"),
    path("merchants/apply/received/", merchant_received, name="merchant_application_received"),
    path("developers/", docs, name="developer_docs"),
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
    path("deliveries/", delivery_lookup, name="delivery_lookup"),
    path(
        "deliveries/<str:reference>/",
        customer_delivery,
        name="customer_delivery",
    ),
    path(f"{API_PREFIX}checkout/", include("apps.checkout.urls")),
    path(API_PREFIX, include("apps.billing.urls")),
    path(f"{API_PREFIX}payments/", include("apps.payments.urls")),
    path(f"{API_PREFIX}settlements/", include("apps.settlements.urls")),
    path(f"{API_PREFIX}checkout/", include("apps.checkout.public_urls")),
]

if settings.DEBUG:
    from drf_spectacular.views import (
        SpectacularAPIView,
        SpectacularRedocView,
        SpectacularSwaggerView,
    )

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
        ),
    ]
