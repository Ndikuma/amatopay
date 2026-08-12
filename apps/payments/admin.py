from django.contrib import admin
from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from .models import IdempotencyRecord, Payment, PaymentStatusHistory

admin.site.register(
    [Payment, PaymentStatusHistory, IdempotencyRecord],
    ReadOnlyAmatoModelAdmin,
)
