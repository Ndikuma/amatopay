from rest_framework.routers import DefaultRouter
from .views import FiduciaryAccountViewSet, FundHoldViewSet, FiduciaryEntryViewSet

router = DefaultRouter()
router.register("accounts", FiduciaryAccountViewSet)
router.register("holds", FundHoldViewSet, basename="fund-hold")
router.register("entries", FiduciaryEntryViewSet, basename="fiduciary-entry")
urlpatterns = router.urls
