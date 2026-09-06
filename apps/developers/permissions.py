from rest_framework.permissions import BasePermission


class HasMerchantApiKey(BasePermission):
    """The request carries a valid merchant API key."""

    def has_permission(self, request, view):
        return bool(
            getattr(request, "api_key", None) and getattr(request, "merchant", None)
        )


class IsActiveMerchant(HasMerchantApiKey):
    """Valid API key AND the merchant account is activated for payments.

    Use this on every endpoint that moves money or creates payment objects.
    Onboarding/status endpoints (e.g. the ping check) use ``HasMerchantApiKey``.
    """

    message = "Your merchant account is not active for payments yet."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.merchant.status == request.merchant.Status.ACTIVE


class IsOperationsUser(BasePermission):
    message = "AmatoPay operations access is required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
        )
