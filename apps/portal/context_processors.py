from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist


def merchant_access(request):
    if not request.user.is_authenticated:
        return {"portal_membership": None}
    try:
        merchant = request.user.merchant_account
    except ObjectDoesNotExist:
        merchant = None
    return {
        "portal_membership": merchant,
    }


def site_context(request):
    """Brand and contact details for every template, sourced from settings/env."""
    return {
        "company_name": settings.COMPANY_NAME,
        "support_email": settings.SUPPORT_EMAIL,
        "sales_email": settings.SALES_EMAIL,
        "developers_email": settings.DEVELOPERS_EMAIL,
        "support_phone": settings.SUPPORT_PHONE,
        "api_base_url": settings.PUBLIC_API_BASE_URL,
    }
