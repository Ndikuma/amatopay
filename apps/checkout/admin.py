from django.contrib import admin
from apps.core.admin_base import AmatoModelAdmin
from .models import PaymentSession

admin.site.register(PaymentSession, AmatoModelAdmin)
