from rest_framework.routers import DefaultRouter

from .claim_views import ProtectionClaimEvidenceViewSet, ProtectionClaimViewSet

router = DefaultRouter()
router.register("cases", ProtectionClaimViewSet, basename="protection-claim")
router.register(
    "evidence", ProtectionClaimEvidenceViewSet, basename="protection-claim-evidence"
)

urlpatterns = router.urls
