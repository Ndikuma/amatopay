import hashlib
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from apps.merchants.models import MerchantApiKey


class MerchantApiKeyAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        raw = request.headers.get("X-Api-Key", "").strip()
        if not raw:
            if not header.startswith(self.keyword + " "):
                return None
            raw = header.split(" ", 1)[1].strip()
        if not raw.startswith("sk_"):
            return None
        prefix = raw[:18]
        digest = hashlib.sha256(raw.encode()).hexdigest()
        key = (
            MerchantApiKey.objects.select_related("merchant")
            .filter(prefix=prefix, secret_hash=digest, active=True)
            .first()
        )
        if not key:
            raise AuthenticationFailed("Invalid AmatoPay API key.")
        if key.expires_at and key.expires_at <= timezone.now():
            raise AuthenticationFailed("Expired AmatoPay API key.")
        if key.merchant.status != key.merchant.Status.ACTIVE:
            raise AuthenticationFailed("Merchant is not active for payments.")
        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at", "updated_at"])
        request.merchant = key.merchant
        request.api_key = key
        return (None, key)

    def authenticate_header(self, request):
        return "Bearer or X-Api-Key"
