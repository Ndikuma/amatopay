from rest_framework import viewsets
from apps.developers.permissions import IsOperationsUser
from .models import (
    SuspiciousTransaction,
    RegulatoryReport,
    DataRetentionRecord,
)
from .serializers import (
    SuspiciousTransactionSerializer,
    RegulatoryReportSerializer,
    DataRetentionRecordSerializer,
)


class SuspiciousTransactionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOperationsUser]
    queryset = SuspiciousTransaction.objects.all().order_by("-created_at")
    serializer_class = SuspiciousTransactionSerializer


class RegulatoryReportViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOperationsUser]
    queryset = RegulatoryReport.objects.all().order_by("-created_at")
    serializer_class = RegulatoryReportSerializer


class DataRetentionRecordViewSet(viewsets.ModelViewSet):
    permission_classes = [IsOperationsUser]
    queryset = DataRetentionRecord.objects.all().order_by("-created_at")
    serializer_class = DataRetentionRecordSerializer
