from rest_framework.routers import DefaultRouter

from .views import (
    DeliveryViewSet,
    ProtectionClaimEvidenceViewSet,
    ProtectionClaimViewSet,
)

router = DefaultRouter()
router.register("claims/cases", ProtectionClaimViewSet, basename="protection-claim")
router.register(
    "claims/evidence",
    ProtectionClaimEvidenceViewSet,
    basename="protection-claim-evidence",
)
router.register("", DeliveryViewSet, basename="delivery")

urlpatterns = router.urls
