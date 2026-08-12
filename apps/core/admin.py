from django.contrib import admin
from .admin_base import ReadOnlyAmatoModelAdmin
from .models import AuditEvent

admin.site.register(AuditEvent, ReadOnlyAmatoModelAdmin)
