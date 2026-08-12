from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.core.exceptions import ObjectDoesNotExist
from apps.merchants.models import MerchantActivity


def _ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (
        forwarded.split(",")[0].strip()
        if forwarded
        else request.META.get("REMOTE_ADDR")
    ) or None


def _record(user, request, action, description):
    if not user:
        return
    try:
        merchant = user.merchant_account
    except ObjectDoesNotExist:
        merchant = None
    if merchant:
        MerchantActivity.objects.create(
            merchant=merchant,
            actor=user,
            action=action,
            description=description,
            ip_address=_ip(request),
            metadata={"user_agent": request.META.get("HTTP_USER_AGENT", "")[:255]},
        )


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    _record(user, request, "account.login", "Signed in to the merchant workspace")


@receiver(user_logged_out)
def record_logout(sender, request, user, **kwargs):
    _record(user, request, "account.logout", "Signed out of the merchant workspace")
