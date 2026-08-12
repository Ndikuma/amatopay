from rest_framework.routers import DefaultRouter
from .views import RefundViewSet

router = DefaultRouter()
router.register("", RefundViewSet, basename="refund")
urlpatterns = router.urls
