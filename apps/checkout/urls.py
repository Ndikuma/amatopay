from rest_framework.routers import DefaultRouter
from django.urls import path
from .payment_views import merchant_alias_verify

from .views import PaymentSessionViewSet

router = DefaultRouter()
router.register("sessions", PaymentSessionViewSet, basename="session")
urlpatterns = [
    path("alias-verifications/", merchant_alias_verify, name="merchant_alias_verify"),
    *router.urls,
]
