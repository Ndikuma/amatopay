from rest_framework.routers import DefaultRouter
from .views import (
    MerchantViewSet,
    MerchantKYBViewSet,
    MerchantDocumentViewSet,
    BeneficialOwnerViewSet,
    MerchantSettlementAccountViewSet,
)

router = DefaultRouter()
router.register("", MerchantViewSet)
router.register("kyb", MerchantKYBViewSet, basename="merchant-kyb")
router.register("documents", MerchantDocumentViewSet, basename="merchant-document")
router.register(
    "beneficial-owners", BeneficialOwnerViewSet, basename="beneficial-owner"
)
router.register(
    "settlement-accounts",
    MerchantSettlementAccountViewSet,
    basename="settlement-account",
)
urlpatterns = router.urls
