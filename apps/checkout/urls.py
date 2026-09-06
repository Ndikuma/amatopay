from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PaymentSessionViewSet, checkout_status, merchant_alias_verify

router = DefaultRouter()
router.register("sessions", PaymentSessionViewSet, basename="session")

urlpatterns = [
    path("alias-verifications/", merchant_alias_verify, name="merchant_alias_verify"),
    path(
        "sessions/<uuid:session_id>/status/",
        checkout_status,
        name="checkout_status",
    ),
    *router.urls,
]
