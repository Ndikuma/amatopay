from django.contrib import admin
from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from .models import IdempotencyKey

admin.site.register(IdempotencyKey, ReadOnlyAmatoModelAdmin)
