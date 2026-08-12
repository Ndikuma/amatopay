from django.core.exceptions import ObjectDoesNotExist


def merchant_access(request):
    if not request.user.is_authenticated:
        return {"portal_membership": None, "portal_role": None}
    try:
        merchant = request.user.merchant_account
    except ObjectDoesNotExist:
        merchant = None
    return {
        "portal_membership": merchant,
        "portal_role": "owner" if merchant else None,
    }
