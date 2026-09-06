from django.urls import path
from . import views

app_name = "portal"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("payments/", views.payments, name="payments"),
    path("payments/<str:reference>/", views.payment_detail, name="payment-detail"),
    path(
        "payments/<str:reference>/confirm-delivery/",
        views.payment_confirm_delivery,
        name="payment-confirm-delivery",
    ),
    path("settlements/", views.settlements, name="settlements"),
    path("refunds/", views.refunds, name="refunds"),
    path("trust/", views.trust, name="trust"),
    path("developers/", views.developers, name="developers"),
    path("developers/keys/create/", views.api_key_create, name="api-key-create"),
    path(
        "developers/keys/<uuid:key_id>/rotate/",
        views.api_key_rotate,
        name="api-key-rotate",
    ),
    path(
        "developers/keys/<uuid:key_id>/revoke/",
        views.api_key_revoke,
        name="api-key-revoke",
    ),
    path("developers/webhooks/create/", views.webhook_create, name="webhook-create"),
    path("developers/webhooks/<uuid:endpoint_id>/toggle/", views.webhook_toggle, name="webhook-toggle"),
    path("developers/webhooks/<uuid:endpoint_id>/rotate-secret/", views.webhook_rotate_secret, name="webhook-rotate-secret"),
    path("developers/webhooks/<uuid:endpoint_id>/test/", views.webhook_test, name="webhook-test"),
    path("profile/", views.profile, name="profile"),
    path("billing/", views.billing, name="billing"),
    path("billing/plans/", views.plan_select, name="plan-select"),
    path("billing/plans/request/", views.billing_request_plan, name="plan-request"),
]
