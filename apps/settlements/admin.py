from django.contrib import admin
from apps.core.admin_base import AmatoModelAdmin
from .models import Settlement, SettlementBatch

admin.site.register([Settlement, SettlementBatch], AmatoModelAdmin)
