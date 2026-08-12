from rest_framework.permissions import BasePermission


class HasMerchantApiKey(BasePermission):
    def has_permission(self, request, view):
        return bool(
            getattr(request, "api_key", None) and getattr(request, "merchant", None)
        )


class IsOperationsUser(BasePermission):
    message = "AmatoPay operations access is required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
        )
