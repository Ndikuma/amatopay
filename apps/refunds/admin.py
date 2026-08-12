from django.contrib import admin
from apps.core.admin_base import AmatoModelAdmin
from .models import Refund

admin.site.register(Refund, AmatoModelAdmin)
