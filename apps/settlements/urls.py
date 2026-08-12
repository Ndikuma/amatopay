from rest_framework.routers import DefaultRouter
from .views import SettlementViewSet

router = DefaultRouter()
router.register("items", SettlementViewSet, basename="settlement")
urlpatterns = router.urls
