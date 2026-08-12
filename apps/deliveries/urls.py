from rest_framework.routers import DefaultRouter
from .views import DeliveryViewSet

router = DefaultRouter()
router.register("", DeliveryViewSet, basename="delivery")
urlpatterns = router.urls
