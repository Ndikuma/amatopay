from django.contrib import admin
from apps.core.admin_base import AmatoModelAdmin
from .models import (
    Delivery,
    DeliveryConfirmation,
    ProtectionClaim,
    ProtectionClaimEvidence,
    ProtectionClaimEvent,
)

admin.site.register(
    [
        Delivery,
        DeliveryConfirmation,
        ProtectionClaim,
        ProtectionClaimEvidence,
        ProtectionClaimEvent,
    ],
    AmatoModelAdmin,
)
