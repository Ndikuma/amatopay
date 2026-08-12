from rest_framework.routers import DefaultRouter
from .views import (
    SuspiciousTransactionViewSet,
    RegulatoryReportViewSet,
    DataRetentionRecordViewSet,
)

router = DefaultRouter()
router.register("suspicious-transactions", SuspiciousTransactionViewSet)
router.register("reports", RegulatoryReportViewSet)
router.register("retention", DataRetentionRecordViewSet)
urlpatterns = router.urls
