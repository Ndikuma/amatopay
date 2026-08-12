from django.contrib import admin
from apps.core.admin_base import AmatoModelAdmin
from .models import (
    SuspiciousTransaction,
    RegulatoryReport,
    DataRetentionRecord,
)

admin.site.register(
    [SuspiciousTransaction, RegulatoryReport, DataRetentionRecord],
    AmatoModelAdmin,
)
